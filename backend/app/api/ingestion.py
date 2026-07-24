from __future__ import annotations

import copy
import tempfile
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
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
from intelligence.config import load_config
from intelligence.pipeline import SignalPipeline
from intelligence.adapters.csv_adapter import CSVAdapter
from intelligence.finding_aggregator import FindingAggregator
from intelligence.importance_score import score_signals
from intelligence.normalize.normalizer import normalize_timeseries
from intelligence.analyzers import (
    BaselineShiftAnalyzer,
    ProphetAnalyzer,
    RupturesAnalyzer,
    STUMPYAnalyzer,
    TrendAnalyzer,
    ZScoreAnomalyAnalyzer,
)

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _provider_defaults(provider: str) -> tuple[dict[str, str], list[str]]:
    provider_lower = provider.lower()
    if provider_lower == "prometheus":
        return ({"metric_name": "metric", "host": "instance"}, ["timestamp", "metric", "value"])
    if provider_lower == "datadog":
        return ({"timestamp": "ts_epoch_ms"}, ["ts_epoch_ms", "metric_name", "value"])
    return ({}, ["timestamp", "metric_name", "value"])


def _build_analyzer(config, analyzer_id: str):
    analyzer_config = config.analysis.analyzers.get(analyzer_id)
    if analyzer_config is None:
        raise HTTPException(status_code=400, detail=f"analyzer '{analyzer_id}' is not configured")

    if analyzer_id == "baseline_shift":
        return BaselineShiftAnalyzer(threshold_percent=float(analyzer_config.params["threshold_percent"]))
    if analyzer_id == "ruptures":
        return RupturesAnalyzer(
            min_segment_size=int(analyzer_config.params.get("min_segment_size", 5)),
            change_threshold=float(analyzer_config.params.get("change_threshold", 1.5)),
        )
    if analyzer_id == "anomaly_zscore":
        return ZScoreAnomalyAnalyzer(
            zscore_threshold=float(analyzer_config.params["zscore_threshold"]),
            grouping_gap=str(analyzer_config.params["grouping_gap"]),
        )
    if analyzer_id == "trend":
        return TrendAnalyzer(min_slope_percent=float(analyzer_config.params["min_slope_percent"]))
    if analyzer_id == "stumpy":
        return STUMPYAnalyzer(
            window_size=int(analyzer_config.params.get("window_size", 20)),
            motif_count=int(analyzer_config.params.get("motif_count", 1)),
            profile_threshold=float(analyzer_config.params.get("profile_threshold", 2.0)),
        )
    if analyzer_id == "prophet":
        return ProphetAnalyzer(
            horizon_points=int(analyzer_config.params.get("horizon_points", 10)),
            changepoint_prior_scale=float(analyzer_config.params.get("changepoint_prior_scale", 0.05)),
            uncertainty_threshold=float(analyzer_config.params.get("uncertainty_threshold", 0.15)),
        )
    raise HTTPException(status_code=400, detail=f"unsupported analyzer '{analyzer_id}'")


def _load_app_config(provider: str = "prometheus") -> object:
    provider_file = _repo_root() / "config" / "providers" / f"{provider}.yaml"
    if provider_file.exists():
        return load_config(provider_file)
    return load_config(_repo_root() / "config" / "config.yaml")


@router.post("/prometheus-run", response_model=PrometheusRunOut)
async def run_prometheus_analysis(
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
        config = copy.deepcopy(_load_app_config("prometheus"))
        config.input.source_type = "prometheus"
        config.input.provider = "prometheus"
        config.input.interval = f"{max(int(payload.step_seconds / 60), 1)}m"
        config.input.service = payload.service
        config.input.metric_name = payload.metric_name
        config.input.timestamp_column = "timestamp"
        config.input.value_column = "value"
        config.input.metric_column = "metric_name"
        config.input.required_columns = ["timestamp", "metric_name", "value"]
        config.input.provider_mappings = {}

        config.output.save_normalized_data = True
        config.output.save_signals = True
        config.output.save_question_answers = True
        config.output.save_embeddings = False
        config.embeddings.enabled = False

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
        raise HTTPException(status_code=500, detail=f"analysis failed: {exc}") from exc

    findings_count = db.execute(
        select(func.count(FindingEntity.id)).where(FindingEntity.analysis_run_id == result.analysis_run_id)
    ).scalar() or 0
    signal_count = db.execute(
        select(func.count(SignalEntity.id)).where(SignalEntity.analysis_run_id == result.analysis_run_id)
    ).scalar() or 0
    behavior_count = db.execute(
        select(func.count(BehaviorFindingEntity.id)).where(BehaviorFindingEntity.analysis_run_id == result.analysis_run_id)
    ).scalar() or 0

    return PrometheusRunOut(
        analysis_run_id=result.analysis_run_id,
        provider="prometheus",
        source_type="prometheus",
        datasource_uid=payload.datasource_uid,
        datasource_name=payload.datasource_name,
        service=payload.service,
        metric_name=payload.metric_name,
        promql=payload.promql,
        from_time=payload.from_time,
        to_time=payload.to_time,
        step_seconds=payload.step_seconds,
        sample_count=payload.sample_count,
        series_count=payload.series_count,
        findings_count=int(findings_count),
        signal_count=int(signal_count),
        behavior_findings_count=int(behavior_count),
        warnings=payload.warnings,
        analyzer_selection_mode=config.analysis.selection_mode,
        analyzer_routing=result.analyzer_routing,
        executed_analyzers=result.executed_analyzers,
    )


@router.post("/csv-run", response_model=CsvRunOut)
async def run_csv_analysis(
    file: UploadFile = File(...),
    provider: str = Form(default="generic"),
    service: str = Form(default="uploaded-service"),
    metric_name: str = Form(default="uploaded_metric"),
    interval: str = Form(default="5m"),
    db: Session = Depends(get_db),
) -> CsvRunOut:
    provider_lower = provider.lower()
    if provider_lower not in {"generic", "prometheus", "datadog"}:
        raise HTTPException(status_code=400, detail="provider must be one of: generic, prometheus, datadog")
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="only .csv uploads are supported")

    upload_dir = _repo_root() / ".tmp_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename).suffix or ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=upload_dir) as handle:
        temp_path = Path(handle.name)
        data = await file.read()
        handle.write(data)

    mapping_defaults, required_defaults = _provider_defaults(provider_lower)

    try:
        template_config = _load_app_config(provider_lower)
        config = copy.deepcopy(template_config)

        config.input.source_type = "csv"
        config.input.provider = provider_lower
        config.input.file_path = str(temp_path)
        config.input.interval = interval
        config.input.service = service
        config.input.metric_name = metric_name
        config.input.provider_mappings = mapping_defaults
        config.input.required_columns = required_defaults
        config.input.timestamp_column = "timestamp"
        config.input.value_column = "value"
        config.input.metric_column = "metric_name"

        config.output.save_normalized_data = True
        config.output.save_signals = True
        config.output.save_question_answers = True
        config.output.save_embeddings = False
        config.embeddings.enabled = False

        result = SignalPipeline(config).run(run_metadata={"file_name": file.filename})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"analysis failed: {exc}") from exc
    finally:
        temp_path.unlink(missing_ok=True)

    # Query findings from database instead of relying on in-memory result
    findings_count = db.execute(
        select(func.count(FindingEntity.id)).where(FindingEntity.analysis_run_id == result.analysis_run_id)
    ).scalar() or 0

    normalized = result.normalized_points
    return CsvRunOut(
        analysis_run_id=result.analysis_run_id,
        file_name=file.filename,
        provider=provider_lower,
        source_type="csv",
        service=service,
        metric_name=metric_name,
        sample_count=int(len(normalized)),
        findings_count=int(findings_count),
    )


@router.post("/csv-validate", response_model=CsvValidationOut)
async def validate_csv_analysis(
    file: UploadFile = File(...),
    provider: str = Form(default="generic"),
    analyzer_id: str = Form(default="ruptures"),
    service: str = Form(default="uploaded-service"),
    metric_name: str = Form(default="uploaded_metric"),
    interval: str = Form(default="5m"),
) -> CsvValidationOut:
    provider_lower = provider.lower()
    if provider_lower not in {"generic", "prometheus", "datadog"}:
        raise HTTPException(status_code=400, detail="provider must be one of: generic, prometheus, datadog")
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="only .csv uploads are supported")

    upload_dir = _repo_root() / ".tmp_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename).suffix or ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=upload_dir) as handle:
        temp_path = Path(handle.name)
        data = await file.read()
        handle.write(data)

    mapping_defaults, required_defaults = _provider_defaults(provider_lower)

    try:
        template_config = _load_app_config(provider_lower)
        config = copy.deepcopy(template_config)

        config.input.source_type = "csv"
        config.input.provider = provider_lower
        config.input.file_path = str(temp_path)
        config.input.interval = interval
        config.input.service = service
        config.input.metric_name = metric_name
        config.input.provider_mappings = mapping_defaults
        config.input.required_columns = required_defaults
        config.input.timestamp_column = "timestamp"
        config.input.value_column = "value"
        config.input.metric_column = "metric_name"

        raw = CSVAdapter(config.input, _repo_root()).load()
        normalized = normalize_timeseries(raw, config.input)
        analyzer = _build_analyzer(config, analyzer_id)
        signals = analyzer.analyze(normalized)
        scored_signals = score_signals(signals, None)
        findings_result = FindingAggregator().aggregate(scored_signals, normalized)

        normalized_preview = normalized.head(25).copy()
        if not normalized_preview.empty:
            normalized_preview["timestamp"] = normalized_preview["timestamp"].astype(str)
        preview_records = normalized_preview.to_dict(orient="records")

        service_name = str(normalized["service"].dropna().iloc[0]) if "service" in normalized.columns and not normalized["service"].dropna().empty else service
        metric_name_value = str(normalized["metric_name"].dropna().iloc[0]) if "metric_name" in normalized.columns and not normalized["metric_name"].dropna().empty else metric_name

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
            for signal in scored_signals
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
            for finding in findings_result.findings
        ]

        return CsvValidationOut(
            provider=provider_lower,
            source_type="csv",
            analyzer_id=analyzer_id,
            service=service_name,
            metric_name=metric_name_value,
            sample_count=int(len(normalized)),
            normalized_preview=preview_records,
            signals=signal_payloads,
            findings=finding_payloads,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"validation failed: {exc}") from exc
    finally:
        temp_path.unlink(missing_ok=True)
