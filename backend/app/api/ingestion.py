from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.api_schema import (
    CsvRunOut,
    CsvValidationOut,
    PrometheusAnalysisRequest,
    PrometheusRunOut,
    ValidationFindingOut,
    ValidationSignalOut,
)
from backend.app.models.db import get_db
from backend.app.models.entities import BehaviorFindingEntity, FindingEntity, SignalEntity
from backend.app.services.timeseries_routing_service import build_csv_routing_config, repo_root
from backend.app.api.errors import internal_error
from intelligence.normalize.normalizer import AUTO_INTERVAL, RESOLVED_INTERVALS_ATTR, VALIDATION_WARNINGS_ATTR
from intelligence.pipeline import SignalPipeline

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])

# Analyses started from these endpoints run one at a time, as they did while they (wrongly) ran on
# the event loop. Run truly in parallel, their catalog writes (save_capabilities, save_questions)
# hit duplicate-key errors and deadlocks. Waiting for it happens in a worker thread, so the event
# loop - /api/health and every other request - stays free.
ANALYSIS_RUN_LOCK = threading.Lock()

# `await file.read()` below loads the entire upload into memory with no cap unless we check it
# ourselves - reject oversized uploads before that read is even fully buffered/written to disk.
# Row count (intelligence/adapters/csv_adapter.py::MAX_CSV_ROWS) is the second layer: byte size
# alone doesn't catch a small-looking file with an enormous row count.
MAX_UPLOAD_BYTES = int(os.getenv("OPS_SIGNALS_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))


async def _read_upload_within_limit(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"CSV upload of {len(data)} bytes exceeds the configured limit of "
                f"{MAX_UPLOAD_BYTES} bytes (set OPS_SIGNALS_MAX_UPLOAD_BYTES to change)."
            ),
        )
    return data


def _build_custom_column_mapping(
    provider: str,
    custom_timestamp_column: str | None,
    custom_value_column: str | None,
    custom_metric_name_column: str | None,
) -> dict[str, str] | None:
    """Ad-hoc, one-time column mapping for the "custom" provider - typed in by the user on the
    upload form, never persisted anywhere, applies to this single upload only. All 3 are required
    together: a partial mapping would just fail later with a confusing "missing columns" error."""
    if provider != "custom":
        return None
    fields = {"timestamp": custom_timestamp_column, "value": custom_value_column, "metric_name": custom_metric_name_column}
    missing = [canonical for canonical, raw in fields.items() if not raw or not raw.strip()]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"provider 'custom' requires all 3 column names to be provided; missing: {missing}",
        )
    return {canonical: raw.strip() for canonical, raw in fields.items()}  # type: ignore[union-attr]


class PreviewPipelineStore:
    def __init__(self) -> None:
        self.analysis_run: dict[str, object] | None = None
        self.normalized_points: pd.DataFrame | None = None
        self.saved_signals: list[object] = []
        self.saved_findings: list[object] = []
        self.answers: list[dict[str, object]] = []
        self.learning_snapshots: list[dict[str, object]] = []

    def init_db(self) -> None:
        return None

    def init_db_from_sql(self, sql_path: Path) -> None:
        return None

    def create_analysis_run(self, payload: dict[str, object]) -> None:
        self.analysis_run = payload

    def save_normalized_points(self, dataframe: pd.DataFrame, analysis_run_id: str | None = None) -> None:
        self.normalized_points = dataframe.copy()

    def update_analysis_run_learning_snapshot(self, analysis_run_id: str, snapshot: dict[str, object]) -> None:
        self.learning_snapshots.append({"analysis_run_id": analysis_run_id, "snapshot": snapshot})

    def save_capabilities(self, capabilities: list[dict[str, object]]) -> None:
        return None

    def save_questions(self, questions: list[dict[str, object]]) -> None:
        return None

    def save_signals(self, signals: list[object], embeddings: dict[int, object] | None = None) -> None:
        self.saved_signals = list(signals)

    def save_findings(self, findings: list[object]) -> None:
        self.saved_findings = list(findings)

    def save_question_answers(self, answers: list[dict[str, object]]) -> None:
        self.answers = list(answers)


def _repo_root() -> Path:
    return repo_root()


# Plain def, so FastAPI runs it in its threadpool: the analysis (pandas, analyzers, database, and
# the Slack post via the findings hook) blocks. As `async def` it ran on the event loop and froze
# every other request, /api/health included, until it finished.
@router.post("/prometheus-run", response_model=PrometheusRunOut)
def run_prometheus_analysis(
    payload: PrometheusAnalysisRequest,
    db: Session = Depends(get_db),
) -> PrometheusRunOut:
    if payload.provider.lower() != "prometheus":
        raise HTTPException(status_code=400, detail="provider must be prometheus")
    if not payload.samples:
        raise HTTPException(status_code=400, detail="samples are required")
    if payload.sample_count != len(payload.samples):
        raise HTTPException(status_code=400, detail="sample_count must match samples length")
    if payload.series_count < 1:
        raise HTTPException(status_code=400, detail="series_count must be at least 1")

    max_series = payload.max_series or 20
    max_samples_per_series = payload.max_samples_per_series or 10000
    if payload.series_count > max_series:
        raise HTTPException(status_code=400, detail=f"series_count {payload.series_count} exceeds max_series {max_series}")
    if payload.sample_count > payload.series_count * max_samples_per_series:
        raise HTTPException(status_code=400, detail=f"sample_count {payload.sample_count} exceeds configured limit")

    records: list[dict[str, object]] = []
    for sample in payload.samples:
        labels = sample.labels or {}
        records.append(
            {
                "timestamp": sample.timestamp,
                "metric_name": sample.metric_name or payload.metric_name,
                "value": sample.value,
                "service": sample.service or payload.service,
                "source": "prometheus",
                "host": labels.get("instance"),
                "namespace": labels.get("namespace"),
                "pod": labels.get("pod"),
                "env": labels.get("env") or labels.get("environment"),
                "series_id": sample.series_id,
                **{f"label_{key}": value for key, value in labels.items() if isinstance(key, str) and isinstance(value, str)},
            }
        )

    try:
        config = build_csv_routing_config(
            provider="prometheus",
            service=payload.service,
            metric_name=payload.metric_name,
            interval=f"{max(int(payload.step_seconds / 60), 1)}m",
            analyzer_id="all",
            preview=False,
        )
        config.input.source_type = "prometheus"
        config.input.required_columns = ["timestamp", "metric_name", "value"]
        config.input.provider_mappings = {}

        with ANALYSIS_RUN_LOCK:
            result = SignalPipeline(config).run_dataframe(
                pd.DataFrame.from_records(records),
                run_metadata={
                    "datasource_uid": payload.datasource_uid,
                    "datasource_name": payload.datasource_name,
                    "promql": payload.promql,
                    "from": payload.from_time.isoformat(),
                    "to": payload.to_time.isoformat(),
                    "step_seconds": payload.step_seconds,
                    "series_count": payload.series_count,
                    "sample_count": payload.sample_count,
                },
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise internal_error("Analysis failed", exc) from exc

    findings_count = db.execute(
        select(func.count(FindingEntity.id)).where(FindingEntity.analysis_run_id == result.analysis_run_id)
    ).scalar() or 0
    signal_count = db.execute(
        select(func.count(SignalEntity.id)).where(SignalEntity.analysis_run_id == result.analysis_run_id)
    ).scalar() or 0
    behavior_count = db.execute(
        select(func.count(BehaviorFindingEntity.id)).where(BehaviorFindingEntity.analysis_run_id == result.analysis_run_id)
    ).scalar() or 0

    stored_service, stored_metric, identity_warnings = _stored_identity(result.normalized_points, payload.service, payload.metric_name)
    return PrometheusRunOut(
        analysis_run_id=result.analysis_run_id,
        provider="prometheus",
        source_type="prometheus",
        datasource_uid=payload.datasource_uid,
        datasource_name=payload.datasource_name,
        service=stored_service,
        metric_name=stored_metric,
        promql=payload.promql,
        from_time=payload.from_time,
        to_time=payload.to_time,
        step_seconds=payload.step_seconds,
        sample_count=payload.sample_count,
        series_count=payload.series_count,
        findings_count=int(findings_count),
        signal_count=int(signal_count),
        behavior_findings_count=int(behavior_count),
        warnings=[*payload.warnings, *identity_warnings],
        analyzer_selection_mode=config.analysis.selection_mode,
        analyzer_routing=result.analyzer_routing,
        executed_analyzers=result.executed_analyzers,
        analyzer_executions=result.analyzer_executions,
    )


@router.post("/csv-run", response_model=CsvRunOut)
async def run_csv_analysis(
    file: UploadFile = File(...),
    provider: str = Form(default="generic"),
    service: str = Form(default="uploaded-service"),
    metric_name: str = Form(default="uploaded_metric"),
    interval: str = Form(default=AUTO_INTERVAL),
    custom_timestamp_column: str | None = Form(default=None),
    custom_value_column: str | None = Form(default=None),
    custom_metric_name_column: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> CsvRunOut:
    provider_lower = provider.lower()
    if provider_lower not in {"generic", "prometheus", "datadog", "custom"}:
        raise HTTPException(status_code=400, detail="provider must be one of: generic, prometheus, datadog, custom")
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="only .csv uploads are supported")

    column_mapping = _build_custom_column_mapping(
        provider_lower, custom_timestamp_column, custom_value_column, custom_metric_name_column
    )
    data = await _read_upload_within_limit(file)
    # The analysis blocks (pandas, analyzers, database, the Slack post): run it in the threadpool,
    # not on the event loop, where it froze every other request until it finished.
    return await run_in_threadpool(
        _run_csv_upload, data, file.filename, provider_lower, service, metric_name, interval, column_mapping, db
    )


def _run_csv_upload(
    data: bytes,
    file_name: str,
    provider_lower: str,
    service: str,
    metric_name: str,
    interval: str,
    column_mapping: dict[str, str] | None,
    db: Session,
) -> CsvRunOut:
    temp_path = _write_upload(data, file_name)
    try:
        config = build_csv_routing_config(
            provider=provider_lower,
            file_path=str(temp_path),
            service=service,
            metric_name=metric_name,
            interval=interval,
            analyzer_id="all",
            preview=False,
            column_mapping=column_mapping,
        )

        with ANALYSIS_RUN_LOCK:
            result = SignalPipeline(config).run(run_metadata={"file_name": file_name})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise internal_error("Analysis failed", exc) from exc
    finally:
        temp_path.unlink(missing_ok=True)

    # Query findings from database instead of relying on in-memory result
    findings_count = db.execute(
        select(func.count(FindingEntity.id)).where(FindingEntity.analysis_run_id == result.analysis_run_id)
    ).scalar() or 0

    normalized = result.normalized_points
    stored_service, stored_metric, identity_warnings = _stored_identity(normalized, service, metric_name)
    interval_fields = _interval_fields(interval, normalized)
    return CsvRunOut(
        analysis_run_id=result.analysis_run_id,
        file_name=file_name,
        provider=provider_lower,
        source_type="csv",
        service=stored_service,
        metric_name=stored_metric,
        sample_count=int(len(normalized)),
        findings_count=int(findings_count),
        **{**interval_fields, "warnings": [*interval_fields["warnings"], *identity_warnings]},
    )


@router.post("/csv-validate", response_model=CsvValidationOut)
async def validate_csv_analysis(
    file: UploadFile = File(...),
    provider: str = Form(default="generic"),
    analyzer_id: str = Form(default="ruptures"),
    service: str = Form(default="uploaded-service"),
    metric_name: str = Form(default="uploaded_metric"),
    interval: str = Form(default=AUTO_INTERVAL),
    analyzer_overrides: str | None = Form(default=None),
    custom_timestamp_column: str | None = Form(default=None),
    custom_value_column: str | None = Form(default=None),
    custom_metric_name_column: str | None = Form(default=None),
) -> CsvValidationOut:
    provider_lower = provider.lower()
    if provider_lower not in {"generic", "prometheus", "datadog", "custom"}:
        raise HTTPException(status_code=400, detail="provider must be one of: generic, prometheus, datadog, custom")
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="only .csv uploads are supported")

    column_mapping = _build_custom_column_mapping(
        provider_lower, custom_timestamp_column, custom_value_column, custom_metric_name_column
    )
    data = await _read_upload_within_limit(file)
    return await run_in_threadpool(
        _validate_csv_upload,
        data,
        file.filename,
        provider_lower,
        analyzer_id,
        service,
        metric_name,
        interval,
        analyzer_overrides,
        column_mapping,
    )


def _validate_csv_upload(
    data: bytes,
    file_name: str,
    provider_lower: str,
    analyzer_id: str,
    service: str,
    metric_name: str,
    interval: str,
    analyzer_overrides: str | None,
    column_mapping: dict[str, str] | None,
) -> CsvValidationOut:
    temp_path = _write_upload(data, file_name)
    try:
        parsed_overrides = _parse_analyzer_overrides(analyzer_overrides)
        requested_analyzer_id = analyzer_id.strip()
        config = build_csv_routing_config(
            provider=provider_lower,
            file_path=str(temp_path),
            service=service,
            metric_name=metric_name,
            interval=interval,
            analyzer_id=requested_analyzer_id,
            preview=True,
            analyzer_overrides=parsed_overrides,
            column_mapping=column_mapping,
        )

        with ANALYSIS_RUN_LOCK:
            result = SignalPipeline(config, store=PreviewPipelineStore()).run(
                run_metadata={"file_name": file_name, "validation_preview": True}
            )
        normalized = result.normalized_points

        normalized_preview = normalized.head(25).copy()
        if not normalized_preview.empty:
            normalized_preview["timestamp"] = normalized_preview["timestamp"].astype(str)
        preview_records = normalized_preview.to_dict(orient="records")

        service_name, metric_name_value, identity_warnings = _stored_identity(normalized, service, metric_name)
        interval_fields = _interval_fields(interval, normalized)

        signal_payloads = [
            ValidationSignalOut(
                signal_id=signal.signal_id,
                signal_type=signal.signal_type,
                analyzer_id=signal.analyzer_id,
                metric_name=signal.metric_name,
                service=signal.service,
                severity=signal.severity,
                confidence=signal.confidence,
                start_time=signal.start_time,
                end_time=signal.end_time,
                summary=signal.summary,
                evidence=signal.evidence,
            )
            for signal in result.signals
        ]
        finding_payloads = [
            ValidationFindingOut(
                metric_name=finding.metric_name,
                service=finding.service,
                title=finding.title,
                summary=finding.summary,
                category=finding.category,
                health_status=finding.health_status,
                importance_score=finding.importance_score,
                investigation_priority=finding.investigation_priority,
                signal_ids=finding.signal_ids,
                comparison_json=finding.comparison_json,
            )
            for finding in result.findings
        ]

        return CsvValidationOut(
            provider=provider_lower,
            source_type="csv",
            analyzer_id=requested_analyzer_id if requested_analyzer_id.lower() not in {"all", "router"} else "router",
            service=service_name,
            metric_name=metric_name_value,
            sample_count=int(len(normalized)),
            **{**interval_fields, "warnings": [*interval_fields["warnings"], *identity_warnings]},
            normalized_preview=preview_records,
            signals=signal_payloads,
            findings=finding_payloads,
            analyzer_selection_mode=config.analysis.selection_mode,
            analyzer_routing=result.analyzer_routing,
            executed_analyzers=result.executed_analyzers,
            analyzer_executions=result.analyzer_executions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        raise internal_error("Validation failed", exc) from exc
    finally:
        temp_path.unlink(missing_ok=True)


def _write_upload(data: bytes, file_name: str) -> Path:
    upload_dir = _repo_root() / ".tmp_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file_name).suffix or ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=upload_dir) as handle:
        handle.write(data)
        return Path(handle.name)


def _stored_identity(normalized: pd.DataFrame, service: str, metric_name: str) -> tuple[str, str, list[str]]:
    """The service and metric the data was stored under, with a warning for each the request named
    differently. A service or metric column in the data wins; the request's value only fills rows
    without one. Responses used to echo the request, so a run named "qa-svc2" reported that while
    its findings were stored under the file's "qa-svc". Several values are listed together."""
    stored: list[str] = []
    warnings: list[str] = []
    for column, requested, label in (("service", service, "service"), ("metric_name", metric_name, "metric name")):
        values = sorted({str(value) for value in normalized[column].dropna()}) if column in normalized.columns else []
        value = ", ".join(values) if values else requested
        stored.append(value)
        if requested and values and requested not in values:
            warnings.append(
                f"Stored under {label} {value} from the data; the {label} you entered ({requested}) only fills rows that have none."
            )
    return stored[0], stored[1], warnings


def _interval_fields(requested: str, normalized: pd.DataFrame) -> dict[str, object]:
    """What the upload asked for, what each series was actually resampled at, and any warning
    about the choice - so a user who left Interval on auto sees the measured value, and one who
    typed an interval finer than the data is told why most slots came out empty."""
    resolved = normalized.attrs.get(RESOLVED_INTERVALS_ATTR) or []
    return {
        "requested_interval": (requested or "").strip() or AUTO_INTERVAL,
        "interval": ", ".join(resolved) if resolved else (requested or "").strip(),
        "warnings": list(normalized.attrs.get(VALIDATION_WARNINGS_ATTR) or []),
    }


def _parse_analyzer_overrides(raw: str | None) -> dict[str, dict[str, object]] | None:
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="analyzer_overrides must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="analyzer_overrides must be an object")

    parsed: dict[str, dict[str, object]] = {}
    for analyzer_id, params in payload.items():
        if not isinstance(analyzer_id, str) or not isinstance(params, dict):
            raise HTTPException(status_code=400, detail="analyzer_overrides must map analyzer ids to parameter objects")
        parsed[analyzer_id] = params
    return parsed
