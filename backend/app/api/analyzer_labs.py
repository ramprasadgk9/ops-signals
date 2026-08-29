from __future__ import annotations

from datetime import datetime
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import re
import tempfile
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
import pandas as pd
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
import yaml

from backend.app.api.admin_analyzers import AnalyzerConfigIn, _ui_to_registry, _validate_analyzer, _write_yaml
from backend.app.api.ingestion import PreviewPipelineStore
from backend.app.models.db import get_db
from backend.app.models.entities import AnalyzerConfigSuggestionEntity, AnalyzerDraftEntity
from backend.app.services.timeseries_routing_service import build_csv_routing_config
from experiments.analyzer_router.analyzer_registry import AnalyzerRegistry
from experiments.analyzer_router.models import SeriesProfile
from experiments.analyzer_router.router import UniversalTimeSeriesRouter
from intelligence.pipeline import SignalPipeline

router = APIRouter(prefix="/api/analyzer-labs", tags=["analyzer-labs"])

PassFailStatus = Literal["pass", "fail", "unknown"]
LibraryStatus = Literal["unknown", "verified", "missing"]
RouterDefinitionStatus = Literal["missing", "draft", "saved"]
RuntimeMappingStatus = Literal["not_implemented", "executable", "mapped_to_missing_runtime"]
SourceStatus = Literal["builtin", "custom"]
RunStatus = Literal["not_run", "passed", "failed"]
DraftStatus = Literal["draft", "routing_tested", "ready_for_backend", "executable", "benchmark_passed"]

REGISTRY_PATH = Path("experiments/analyzer_router/analyzer_registry.yaml")
CUSTOM_ANALYZERS_PATH = Path("config/custom_analyzers.yaml")
ANALYZERS_CONFIG_PATH = Path("config/analyzers.yaml")
PYTHON_IMPORT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")

EXECUTABLE_ANALYZER_IDS = {
    "anomaly_zscore",
    "baseline_shift",
    "prophet",
    "pyod_outlier",
    "ruptures",
    "stumpy",
    "trend",
}

RUNTIME_ALIASES = {
    "trend_regression": "trend",
}


class AnalyzerConfigSuggestionIn(BaseModel):
    analyzer_id: str = Field(min_length=1, max_length=64)
    lab_name: str = Field(min_length=1, max_length=128)
    suggestion_name: str = Field(min_length=1, max_length=256)
    yaml_text: str = Field(min_length=1)
    implementation_json: dict = Field(default_factory=dict)
    finding_rules_json: dict = Field(default_factory=dict)
    benchmark_summary_json: dict = Field(default_factory=dict)
    pass_fail_status: PassFailStatus = "unknown"
    created_by: str = Field(default="local", max_length=128)


class AnalyzerConfigSuggestionOut(AnalyzerConfigSuggestionIn):
    id: int
    created_at: datetime


class LibraryCheckIn(BaseModel):
    package: str = Field(min_length=1, max_length=128)
    import_name: str | None = Field(default=None, max_length=128)


class LibraryCheckOut(BaseModel):
    package: str
    import_name: str
    installed: bool
    status: LibraryStatus
    version: str | None = None
    error: str | None = None
    suggested_install: str | None = None


class AnalyzerReadinessOut(BaseModel):
    analyzer_id: str
    library: str | None = None
    import_name: str | None = None
    library_importable: bool | None = None
    library_status: LibraryStatus = "unknown"
    library_error: str | None = None
    router_definition_exists: bool
    router_definition_status: RouterDefinitionStatus
    router_definition_source: SourceStatus | None = None
    config_exists: bool
    runtime_mapping: str
    runtime_mapping_status: RuntimeMappingStatus
    backend_implementation_exists: bool
    executable: bool
    execution_test_status: RunStatus = "not_run"
    benchmark_status: RunStatus = "not_run"


class RuntimeMappingOut(BaseModel):
    id: str
    label: str
    executable: bool
    description: str


class AnalyzerDraftIn(BaseModel):
    config: AnalyzerConfigIn
    created_by: str = Field(default="local", max_length=128)


class AnalyzerDraftOut(BaseModel):
    id: int
    analyzer_id: str
    display_name: str
    status: DraftStatus
    config: AnalyzerConfigIn
    readiness: dict = Field(default_factory=dict)
    routing_test: dict = Field(default_factory=dict)
    execution_test: dict = Field(default_factory=dict)
    benchmark: dict = Field(default_factory=dict)
    created_by: str
    promoted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AnalyzerDraftYamlPreviewOut(BaseModel):
    analyzer_id: str
    yaml_text: str


class ExecutionTestOut(BaseModel):
    analyzer_id: str
    available: bool
    status: RunStatus | Literal["unavailable"]
    reason: str
    runtime_mapping: str
    sample_count: int = 0
    signal_count: int = 0
    finding_count: int = 0


class LabRoutingTestIn(BaseModel):
    config: AnalyzerConfigIn
    lab_profile: Literal["zscore_anomaly", "pyod_outlier", "prophet_forecast", "ruptures_change_point", "stumpy_motif", "trend"]


class LabRoutingTestOut(BaseModel):
    analyzer_id: str
    lab_profile: str
    lab_profile_label: str
    detected_profiles: list[str]
    recommendation: str
    final_score: float
    eligible: bool
    runtime_status: str
    reasons: list[str]
    matched_rules: list[dict] = Field(default_factory=list)


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    return loaded if isinstance(loaded, dict) else {}


def _registry_definitions() -> dict[str, tuple[dict, SourceStatus]]:
    definitions: dict[str, tuple[dict, SourceStatus]] = {}
    builtin = _read_yaml(REGISTRY_PATH).get("analyzers", {})
    if isinstance(builtin, dict):
        definitions.update({key: (value or {}, "builtin") for key, value in builtin.items()})

    custom = _read_yaml(CUSTOM_ANALYZERS_PATH).get("analyzers", {})
    if isinstance(custom, dict):
        definitions.update({key: (value or {}, "custom") for key, value in custom.items()})
    return definitions


def _configured_analyzers() -> set[str]:
    config = _read_yaml(ANALYZERS_CONFIG_PATH)
    analyzers = config.get("analysis", {}).get("analyzers", {})
    return set(analyzers.keys()) if isinstance(analyzers, dict) else set()


def _runtime_mappings() -> list[RuntimeMappingOut]:
    descriptions = {
        "baseline_shift": "Existing baseline-shift runtime backed by change-point logic.",
        "anomaly_zscore": "Existing simple z-score anomaly runtime.",
        "pyod_outlier": "Existing PyOD-backed point-outlier runtime.",
        "stumpy": "Existing STUMPY motif runtime.",
        "prophet": "Existing Prophet forecast runtime.",
        "trend": "Existing trend regression runtime.",
        "not_implemented": "Config-only analyzer; can be routed but cannot execute yet.",
    }
    ids = ["baseline_shift", "anomaly_zscore", "pyod_outlier", "stumpy", "prophet", "trend", "not_implemented"]
    return [
        RuntimeMappingOut(
            id=mapping_id,
            label=mapping_id.replace("_", " ").title(),
            executable=mapping_id in EXECUTABLE_ANALYZER_IDS,
            description=descriptions[mapping_id],
        )
        for mapping_id in ids
    ]


def _resolve_runtime_mapping(runtime_mapping: str | None, analyzer_id: str) -> str:
    candidate = (runtime_mapping or analyzer_id).strip() or analyzer_id
    return RUNTIME_ALIASES.get(candidate, candidate)


def _library_check(package: str, import_name: str | None = None) -> LibraryCheckOut:
    cleaned_package = package.strip()
    cleaned_import_name = (import_name or cleaned_package).strip().replace("-", "_")
    if not PYTHON_IMPORT_RE.match(cleaned_import_name):
        return LibraryCheckOut(
            package=cleaned_package,
            import_name=cleaned_import_name,
            installed=False,
            status="missing",
            error="Import name must be a Python module path, such as greykite or greykite.framework.",
            suggested_install=f"pip install {cleaned_package}" if cleaned_package else None,
        )

    try:
        import_module(cleaned_import_name)
    except Exception as exc:  # pragma: no cover - exact import errors vary by package
        return LibraryCheckOut(
            package=cleaned_package,
            import_name=cleaned_import_name,
            installed=False,
            status="missing",
            error=str(exc),
            suggested_install=f"pip install {cleaned_package}",
        )

    package_version: str | None = None
    try:
        package_version = version(cleaned_package)
    except PackageNotFoundError:
        package_version = None

    return LibraryCheckOut(
        package=cleaned_package,
        import_name=cleaned_import_name,
        installed=True,
        status="verified",
        version=package_version,
    )


def _draft_to_out(row: AnalyzerDraftEntity) -> AnalyzerDraftOut:
    return AnalyzerDraftOut(
        id=row.id,
        analyzer_id=row.analyzer_id,
        display_name=row.display_name,
        status=row.status,  # type: ignore[arg-type]
        config=AnalyzerConfigIn(**(row.config_json or {})),
        readiness=row.readiness_json or {},
        routing_test=row.routing_test_json or {},
        execution_test=row.execution_test_json or {},
        benchmark=row.benchmark_json or {},
        created_by=row.created_by or "local",
        promoted_at=row.promoted_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _draft_yaml_text(config: AnalyzerConfigIn) -> str:
    return yaml.safe_dump(
        {"analyzers": {config.analyzer_id: _ui_to_registry(config)}},
        sort_keys=False,
    )


def _lab_series_profile(lab_profile: str, minimum_samples: int) -> SeriesProfile:
    sample_count = max(minimum_samples, 120)
    base = {
        "original_sample_count": sample_count,
        "valid_sample_count": sample_count,
        "invalid_timestamp_count": 0,
        "invalid_value_count": 0,
        "missing_percentage": 0.0,
        "duplicate_timestamp_count": 0,
        "sampling_interval_seconds": 300,
        "duration_seconds": 300 * sample_count,
        "irregular_sampling_percentage": 0.0,
        "interpolated_sample_count": 0,
        "interpolated_percentage": 0.0,
        "constant_value_percentage": 0.0,
        "sample_count": sample_count,
        "regular_sampling": True,
        "mean": 50.0,
        "stddev": 5.0,
        "minimum": 30.0,
        "maximum": 90.0,
        "variance": 25.0,
        "trend_slope": 0.0,
        "trend_strength": 0.1,
        "seasonality_strength": 0.1,
        "spikiness": 0.1,
        "shift_index": 0.0,
        "autocorrelation": None,
        "trend_fit_r2": 0.1,
        "trend_abruptness_ratio": 0.0,
        "seasonality_dominant_lag": None,
        "seasonality_peak_strength": 0.1,
        "transient_spike_count": 0,
        "persistent_jump_count": 0,
        "detected_profiles": [],
        "notes": [],
    }
    profiles = {
        "zscore_anomaly": {
            "label": "Z-Score anomaly generated data",
            "detected_profiles": ["anomaly", "spike", "outlier"],
            "spikiness": 0.86,
            "transient_spike_count": 8,
            "maximum": 130.0,
            "stddev": 12.0,
            "variance": 144.0,
        },
        "pyod_outlier": {
            "label": "PyOD outlier generated data",
            "detected_profiles": ["outlier", "anomaly", "spike"],
            "spikiness": 0.9,
            "transient_spike_count": 10,
            "maximum": 140.0,
            "stddev": 14.0,
            "variance": 196.0,
        },
        "prophet_forecast": {
            "label": "Prophet forecast generated data",
            "detected_profiles": ["forecast", "seasonal", "trend"],
            "trend_strength": 0.45,
            "seasonality_strength": 0.7,
            "seasonality_peak_strength": 0.7,
            "seasonality_dominant_lag": 24,
            "trend_fit_r2": 0.72,
        },
        "ruptures_change_point": {
            "label": "Ruptures change-point generated data",
            "detected_profiles": ["baseline_shift", "regime_change", "mixed"],
            "shift_index": 0.72,
            "persistent_jump_count": 1,
            "trend_abruptness_ratio": 0.9,
            "mean": 65.0,
            "maximum": 95.0,
        },
        "stumpy_motif": {
            "label": "STUMPY motif generated data",
            "detected_profiles": ["repeating_pattern", "seasonal", "motif"],
            "seasonality_strength": 0.82,
            "seasonality_peak_strength": 0.82,
            "seasonality_dominant_lag": 20,
            "autocorrelation": 0.8,
        },
        "trend": {
            "label": "Trend generated data",
            "detected_profiles": ["trend"],
            "trend_slope": 0.35,
            "trend_strength": 0.9,
            "trend_fit_r2": 0.86,
            "maximum": 120.0,
        },
    }
    base.update(profiles[lab_profile])
    base.pop("label")
    return SeriesProfile(**base)


def _lab_profile_label(lab_profile: str) -> str:
    return {
        "zscore_anomaly": "Z-Score anomaly generated data",
        "pyod_outlier": "PyOD outlier generated data",
        "prophet_forecast": "Prophet forecast generated data",
        "ruptures_change_point": "Ruptures change-point generated data",
        "stumpy_motif": "STUMPY motif generated data",
        "trend": "Trend generated data",
    }[lab_profile]


def _to_out(row: AnalyzerConfigSuggestionEntity) -> AnalyzerConfigSuggestionOut:
    return AnalyzerConfigSuggestionOut(
        id=row.id,
        analyzer_id=row.analyzer_id,
        lab_name=row.lab_name,
        suggestion_name=row.suggestion_name,
        yaml_text=row.yaml_text,
        implementation_json=row.implementation_json or {},
        finding_rules_json=row.finding_rules_json or {},
        benchmark_summary_json=row.benchmark_summary_json or {},
        pass_fail_status=row.pass_fail_status or "unknown",
        created_by=row.created_by or "local",
        created_at=row.created_at,
    )


@router.get("/runtime-mappings", response_model=list[RuntimeMappingOut])
def list_runtime_mappings() -> list[RuntimeMappingOut]:
    return _runtime_mappings()


@router.post("/libraries/check", response_model=LibraryCheckOut)
def check_library(payload: LibraryCheckIn) -> LibraryCheckOut:
    return _library_check(payload.package, payload.import_name)


@router.get("/readiness/{analyzer_id}", response_model=AnalyzerReadinessOut)
def get_analyzer_readiness(
    analyzer_id: str,
    library: str | None = Query(default=None),
    import_name: str | None = Query(default=None),
    runtime_mapping: str | None = Query(default=None),
) -> AnalyzerReadinessOut:
    definitions = _registry_definitions()
    definition_tuple = definitions.get(analyzer_id)
    definition = definition_tuple[0] if definition_tuple else {}
    source = definition_tuple[1] if definition_tuple else None
    admin_metadata = definition.get("admin_metadata", {}) if isinstance(definition, dict) else {}
    if not isinstance(admin_metadata, dict):
        admin_metadata = {}

    resolved_library = library or admin_metadata.get("library")
    resolved_import_name = import_name or resolved_library
    raw_runtime_mapping = runtime_mapping or admin_metadata.get("runtime_mapping") or analyzer_id
    executable_mapping = _resolve_runtime_mapping(raw_runtime_mapping, analyzer_id)

    configured = _configured_analyzers()
    config_exists = analyzer_id in configured or executable_mapping in configured
    backend_implementation_exists = executable_mapping in EXECUTABLE_ANALYZER_IDS
    runtime_status: RuntimeMappingStatus = "executable" if backend_implementation_exists else "not_implemented"
    if raw_runtime_mapping and raw_runtime_mapping != executable_mapping and not backend_implementation_exists:
        runtime_status = "mapped_to_missing_runtime"

    library_result: LibraryCheckOut | None = None
    if resolved_library:
        library_result = _library_check(str(resolved_library), str(resolved_import_name or resolved_library))

    return AnalyzerReadinessOut(
        analyzer_id=analyzer_id,
        library=str(resolved_library) if resolved_library else None,
        import_name=str(resolved_import_name) if resolved_import_name else None,
        library_importable=library_result.installed if library_result else None,
        library_status=library_result.status if library_result else "unknown",
        library_error=library_result.error if library_result else None,
        router_definition_exists=definition_tuple is not None,
        router_definition_status="saved" if definition_tuple is not None else "missing",
        router_definition_source=source,
        config_exists=config_exists,
        runtime_mapping=raw_runtime_mapping,
        runtime_mapping_status=runtime_status,
        backend_implementation_exists=backend_implementation_exists,
        executable=backend_implementation_exists and config_exists and (library_result.installed if library_result else True),
    )


@router.get("/drafts", response_model=list[AnalyzerDraftOut])
def list_analyzer_drafts(db: Session = Depends(get_db)) -> list[AnalyzerDraftOut]:
    rows = db.execute(select(AnalyzerDraftEntity).order_by(AnalyzerDraftEntity.updated_at.desc())).scalars().all()
    return [_draft_to_out(row) for row in rows]


@router.post("/drafts", response_model=AnalyzerDraftOut)
def save_analyzer_draft(payload: AnalyzerDraftIn, db: Session = Depends(get_db)) -> AnalyzerDraftOut:
    _validate_analyzer(payload.config)
    readiness = get_analyzer_readiness(
        analyzer_id=payload.config.analyzer_id,
        library=payload.config.library,
        import_name=payload.config.library,
        runtime_mapping=payload.config.runtime_mapping,
    ).model_dump()
    existing = db.execute(
        select(AnalyzerDraftEntity).where(AnalyzerDraftEntity.analyzer_id == payload.config.analyzer_id)
    ).scalar_one_or_none()
    now = datetime.utcnow()
    if existing is None:
        row = AnalyzerDraftEntity(
            analyzer_id=payload.config.analyzer_id,
            display_name=payload.config.display_name,
            status="draft",
            config_json=payload.config.model_dump(),
            readiness_json=readiness,
            created_by=payload.created_by,
            updated_at=now,
        )
        db.add(row)
    else:
        row = existing
        row.display_name = payload.config.display_name
        row.config_json = payload.config.model_dump()
        row.readiness_json = readiness
        row.status = "draft" if row.status not in {"executable", "benchmark_passed"} else row.status
        row.updated_at = now
    db.commit()
    db.refresh(row)
    return _draft_to_out(row)


@router.post("/drafts/{draft_id}/routing-test", response_model=AnalyzerDraftOut)
def mark_routing_tested(draft_id: int, db: Session = Depends(get_db)) -> AnalyzerDraftOut:
    row = db.get(AnalyzerDraftEntity, draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Analyzer draft not found")
    row.routing_test_json = {"status": "passed", "message": "Routing test passed from Add Analyzer workbench."}
    row.status = "routing_tested"
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _draft_to_out(row)


@router.post("/drafts/{draft_id}/promote", response_model=AnalyzerDraftOut)
def promote_analyzer_draft(draft_id: int, db: Session = Depends(get_db)) -> AnalyzerDraftOut:
    row = db.get(AnalyzerDraftEntity, draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Analyzer draft not found")
    config = AnalyzerConfigIn(**(row.config_json or {}))
    _validate_analyzer(config)
    custom = _read_yaml(CUSTOM_ANALYZERS_PATH)
    analyzers = custom.setdefault("analyzers", {})
    analyzers[config.analyzer_id] = _ui_to_registry(config)
    _write_yaml(CUSTOM_ANALYZERS_PATH, custom)
    readiness = get_analyzer_readiness(
        analyzer_id=config.analyzer_id,
        library=config.library,
        import_name=config.library,
        runtime_mapping=config.runtime_mapping,
    ).model_dump()
    row.readiness_json = readiness
    row.status = "executable" if readiness.get("executable") else "ready_for_backend"
    row.promoted_at = datetime.utcnow()
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _draft_to_out(row)


@router.get("/drafts/{draft_id}/yaml-preview", response_model=AnalyzerDraftYamlPreviewOut)
def preview_analyzer_draft_yaml(draft_id: int, db: Session = Depends(get_db)) -> AnalyzerDraftYamlPreviewOut:
    row = db.get(AnalyzerDraftEntity, draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Analyzer draft not found")
    config = AnalyzerConfigIn(**(row.config_json or {}))
    _validate_analyzer(config)
    return AnalyzerDraftYamlPreviewOut(analyzer_id=config.analyzer_id, yaml_text=_draft_yaml_text(config))


@router.post("/drafts/{draft_id}/execution-test", response_model=ExecutionTestOut)
def run_execution_test(draft_id: int, db: Session = Depends(get_db)) -> ExecutionTestOut:
    row = db.get(AnalyzerDraftEntity, draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Analyzer draft not found")
    config = AnalyzerConfigIn(**(row.config_json or {}))
    runtime_mapping = _resolve_runtime_mapping(config.runtime_mapping, config.analyzer_id)
    if runtime_mapping not in EXECUTABLE_ANALYZER_IDS:
        if runtime_mapping == "not_implemented":
            reason = (
                "Execution test unavailable because this analyzer is recommendation-only "
                "until backend runtime mapping is added."
            )
        else:
            reason = f"Execution test unavailable because runtime mapping '{config.runtime_mapping}' has no backend implementation yet."
        result = ExecutionTestOut(
            analyzer_id=config.analyzer_id,
            available=False,
            status="unavailable",
            reason=reason,
            runtime_mapping=config.runtime_mapping,
        )
    else:
        sample_count = max(config.min_samples, 90)
        timestamps = pd.date_range(end=pd.Timestamp.utcnow(), periods=sample_count, freq="5min")
        values = [50.0 + (idx * 0.08) for idx in range(sample_count)]
        dataframe = pd.DataFrame({"timestamp": timestamps.astype(str), "value": values})
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as handle:
            temp_path = Path(handle.name)
            dataframe.to_csv(temp_path, index=False)
        try:
            pipeline_config = build_csv_routing_config(
                provider="generic",
                file_path=str(temp_path),
                service="execution-test",
                metric_name=f"{config.analyzer_id}_execution_test",
                interval="5m",
                analyzer_id=runtime_mapping,
                preview=True,
                analyzer_overrides={runtime_mapping: config.runtime_params or {}},
            )
            pipeline_result = SignalPipeline(pipeline_config, store=PreviewPipelineStore()).run(
                run_metadata={"file_name": temp_path.name, "execution_test": True}
            )
            result = ExecutionTestOut(
                analyzer_id=config.analyzer_id,
                available=True,
                status="passed",
                reason="Execution test passed through the CSV validation pipeline.",
                runtime_mapping=config.runtime_mapping,
                sample_count=len(pipeline_result.normalized_points),
                signal_count=len(pipeline_result.signals),
                finding_count=len(pipeline_result.findings),
            )
        except Exception as exc:  # pragma: no cover - analyzer dependencies vary locally
            result = ExecutionTestOut(
                analyzer_id=config.analyzer_id,
                available=True,
                status="failed",
                reason=f"Execution test failed: {exc}",
                runtime_mapping=config.runtime_mapping,
                sample_count=sample_count,
            )
        finally:
            temp_path.unlink(missing_ok=True)
    row.execution_test_json = result.model_dump()
    row.updated_at = datetime.utcnow()
    db.commit()
    return result


@router.post("/lab-routing-test", response_model=LabRoutingTestOut)
def test_routing_with_lab_data(payload: LabRoutingTestIn) -> LabRoutingTestOut:
    _validate_analyzer(payload.config)
    registry_data = {
        "registry_version": "lab-routing-preview",
        "analyzers": _read_yaml(REGISTRY_PATH).get("analyzers", {}),
    }
    custom = _read_yaml(CUSTOM_ANALYZERS_PATH).get("analyzers", {})
    if isinstance(custom, dict):
        registry_data["analyzers"].update(custom)
    registry_data["analyzers"][payload.config.analyzer_id] = _ui_to_registry(payload.config)
    temp_path = CUSTOM_ANALYZERS_PATH.parent / ".lab_routing_preview_registry.yaml"
    _write_yaml(temp_path, registry_data)
    try:
        router_service = UniversalTimeSeriesRouter(registry=AnalyzerRegistry(temp_path))
        profile = _lab_series_profile(payload.lab_profile, payload.config.min_samples)
        decision = next(
            decision
            for decision in router_service.recommend_analyzers_for_profile(profile)
            if decision.analyzer == payload.config.analyzer_id
        )
        return LabRoutingTestOut(
            analyzer_id=decision.analyzer,
            lab_profile=payload.lab_profile,
            lab_profile_label=_lab_profile_label(payload.lab_profile),
            detected_profiles=profile.detected_profiles,
            recommendation=decision.recommendation,
            final_score=decision.final_score,
            eligible=decision.eligible,
            runtime_status="executable" if payload.config.runtime_mapping != "not_implemented" else "config_only",
            reasons=decision.reasons,
            matched_rules=decision.parameters_tested.get("matched_scoring_rules", []),
        )
    finally:
        temp_path.unlink(missing_ok=True)


@router.delete("/drafts/{draft_id}", response_model=dict)
def delete_analyzer_draft(draft_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(AnalyzerDraftEntity, draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Analyzer draft not found")
    db.delete(row)
    db.commit()
    return {"deleted": 1}


@router.get("/config-suggestions", response_model=list[AnalyzerConfigSuggestionOut])
def list_config_suggestions(
    analyzer_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[AnalyzerConfigSuggestionOut]:
    stmt = select(AnalyzerConfigSuggestionEntity).order_by(AnalyzerConfigSuggestionEntity.created_at.desc())
    if analyzer_id:
        stmt = stmt.where(AnalyzerConfigSuggestionEntity.analyzer_id == analyzer_id)
    rows = db.execute(stmt).scalars().all()
    return [_to_out(row) for row in rows]


@router.post("/config-suggestions", response_model=AnalyzerConfigSuggestionOut)
def create_config_suggestion(
    payload: AnalyzerConfigSuggestionIn,
    db: Session = Depends(get_db),
) -> AnalyzerConfigSuggestionOut:
    row = AnalyzerConfigSuggestionEntity(
        analyzer_id=payload.analyzer_id,
        lab_name=payload.lab_name,
        suggestion_name=payload.suggestion_name,
        yaml_text=payload.yaml_text,
        implementation_json=payload.implementation_json,
        finding_rules_json=payload.finding_rules_json,
        benchmark_summary_json=payload.benchmark_summary_json,
        pass_fail_status=payload.pass_fail_status,
        created_by=payload.created_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.delete("/config-suggestions/{suggestion_id}", response_model=dict)
def delete_config_suggestion(suggestion_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(AnalyzerConfigSuggestionEntity, suggestion_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Analyzer config suggestion not found")
    db.delete(row)
    db.commit()
    return {"deleted": 1}


@router.delete("/config-suggestions", response_model=dict)
def clear_config_suggestions(
    analyzer_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    stmt = delete(AnalyzerConfigSuggestionEntity)
    if analyzer_id:
        stmt = stmt.where(AnalyzerConfigSuggestionEntity.analyzer_id == analyzer_id)
    result = db.execute(stmt)
    db.commit()
    return {"deleted": result.rowcount or 0}
