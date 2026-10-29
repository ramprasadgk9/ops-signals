from __future__ import annotations

from datetime import datetime
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import re
import tempfile
from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query
import pandas as pd
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
import yaml

from backend.app.api.admin_analyzers import (
    AnalyzerConfigIn,
    _ui_to_registry,
    _validate_analyzer,
    _write_yaml,
    http_spec_from_runtime_params,
)
from backend.app.api.ingestion import PreviewPipelineStore
from backend.app.models.db import get_db
from backend.app.models.entities import AnalyzerConfigSuggestionEntity, AnalyzerDraftEntity, NormalizedPoint
from backend.app.services.run_points import run_points_filter
from backend.app.security import require_file_writes
from backend.app.services.timeseries_routing_service import build_csv_routing_config
from experiments.analyzer_router.analyzer_registry import AnalyzerRegistry
from experiments.analyzer_router.models import SeriesProfile
from experiments.analyzer_router.router import UniversalTimeSeriesRouter
from intelligence.analyzer_registry import instantiate as instantiate_analyzer, load_registrations
from intelligence.analyzers.http_analyzer import safe_url
from intelligence.config import InputConfig
from intelligence.normalize.normalizer import normalize_timeseries
from intelligence.pipeline import SignalPipeline
from intelligence.series_identity import analyzer_slot

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
CUSTOM_ANALYZER_ADAPTER_DIR = Path("backend/app/analyzers/custom")
# Where Promote / Add backend support actually register a custom analyzer with the real
# pipeline+router (see intelligence/analyzer_registry.py and
# experiments/analyzer_router/analyzer_registry.py's additive merge) - CUSTOM_ANALYZERS_PATH
# above is legacy: nothing in production reads it, it only still exists for
# backend/app/api/admin_analyzers.py's older simple CRUD surface. One file per analyzer avoids
# read-modify-write races between concurrent promotions.
CUSTOM_ANALYZER_REGISTRY_DIR = Path("config/analyzer_registry.d")
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


class BackendSupportOut(BaseModel):
    analyzer_id: str
    implementation_status: str
    module: str
    class_name: str
    adapter_path: str
    created: bool
    message: str


class AdapterSourceOut(BaseModel):
    analyzer_id: str
    adapter_path: str
    source: str


class ExecutionTestOut(BaseModel):
    analyzer_id: str
    available: bool
    status: RunStatus | Literal["unavailable"]
    reason: str
    runtime_mapping: str
    sample_count: int = 0
    signal_count: int = 0
    finding_count: int = 0
    data_source: Literal["real", "synthetic"] = "synthetic"


class ExecutionTestIn(BaseModel):
    """Optional real sample to test against instead of synthetic data - same (service, metric,
    analysis_run_id) tuple the metric-analyzer-recommendations sample picker already surfaces."""

    analysis_run_id: str | None = None
    service: str | None = None


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

    for registration in _load_custom_registrations():
        definitions[registration.analyzer_id] = (
            {
                "display_name": registration.display_name,
                "supported_profiles": registration.router.supported_profiles,
                "eligibility_rules": registration.router.eligibility_rules,
                "scoring_rules": registration.router.scoring_rules,
                "explanation_templates": registration.router.explanation_templates,
            },
            "custom",
        )
    return definitions


def _configured_analyzers() -> set[str]:
    config = _read_yaml(ANALYZERS_CONFIG_PATH)
    analyzers = config.get("analysis", {}).get("analyzers", {})
    ids = set(analyzers.keys()) if isinstance(analyzers, dict) else set()
    ids.update(registration.analyzer_id for registration in _load_custom_registrations())
    return ids


def _load_custom_registrations() -> list:
    """Everything in config/analyzer_registry.d/ except builtin.yml, which holds the 7 real
    built-in analyzers, not anything a user promoted through this wizard."""
    if not CUSTOM_ANALYZER_REGISTRY_DIR.exists():
        return []
    return [reg for reg in load_registrations(CUSTOM_ANALYZER_REGISTRY_DIR) if reg.source_file != "builtin.yml"]


def _custom_registration_path(analyzer_id: str) -> Path:
    return CUSTOM_ANALYZER_REGISTRY_DIR / f"custom_{analyzer_id}.yml"


def _custom_adapter_path(analyzer_id: str) -> Path:
    return CUSTOM_ANALYZER_ADAPTER_DIR / f"{analyzer_id}.py"


def _custom_registration_for(analyzer_id: str):
    """Only returns a registration if this analyzer_id was actually promoted (has a real entry
    in config/analyzer_registry.d/) - deliberately does NOT just check whether a same-named file
    happens to exist under CUSTOM_ANALYZER_ADAPTER_DIR, since that directory can contain
    legitimately committed example adapters (e.g. backend/app/analyzers/custom/
    statsforecast_forecast.py) that were never promoted through this specific draft at all."""
    return next(
        (reg for reg in _load_custom_registrations() if reg.analyzer_id == analyzer_id),
        None,
    )


def _config_to_registration_dict(config: AnalyzerConfigIn) -> dict:
    """Builds the config/analyzer_registry.d/ registration for a custom analyzer authored
    through the Add Analyzer wizard - the shape intelligence/analyzer_registry.py's loader (and,
    for its router block, experiments/analyzer_router/analyzer_registry.py's additive merge)
    expects. Reuses _ui_to_registry's already-validated eligibility/scoring rule flattening
    rather than re-deriving it. An analyzer on the "hosted API or model" path gets an http: block
    instead of a class_path - it runs through HttpAnalyzer and needs no Python file."""
    legacy_shape = _ui_to_registry(config)
    http_spec = http_spec_from_runtime_params(config.runtime_params)
    runtime = (
        {"http": http_spec}
        if http_spec is not None
        else {"class_path": f"backend.app.analyzers.custom.{config.analyzer_id}.{_adapter_class_name(config.analyzer_id)}"}
    )
    return {
        "display_name": legacy_shape["display_name"],
        **({"description": config.description.strip()} if config.description.strip() else {}),
        "enabled": config.enabled,
        **runtime,
        "router": {
            "supported_profiles": legacy_shape["supported_profiles"],
            "eligibility_rules": legacy_shape["eligibility_rules"],
            "scoring_rules": legacy_shape["scoring_rules"],
            "explanation_templates": legacy_shape["explanation_templates"],
        },
        "runtime_params": dict(config.runtime_params or {}),
        **({"always_run": True} if config.always_run else {}),
    }


def _executable_analyzer_ids() -> set[str]:
    """The static 7 built-ins, plus any custom analyzer whose adapter stub file has actually
    been created (Add backend support) - matching what SignalPipeline._build_analyzers() would
    really be able to construct, instead of the old fixed set that could never include a custom
    analyzer no matter how far through the wizard it had progressed."""
    ids = set(EXECUTABLE_ANALYZER_IDS)
    for registration in _load_custom_registrations():
        if registration.http is not None or _custom_adapter_path(registration.analyzer_id).exists():
            ids.add(registration.analyzer_id)
    return ids


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
        {"analyzers": {config.analyzer_id: _registry_with_pending_implementation(config)}},
        sort_keys=False,
    )


def _adapter_class_name(analyzer_id: str) -> str:
    return "".join(part.capitalize() for part in analyzer_id.split("_") if part) + "Analyzer"


def _implementation_metadata(config: AnalyzerConfigIn, status: str = "pending") -> dict[str, str]:
    return {
        "type": "adapter",
        "module": f"backend.app.analyzers.custom.{config.analyzer_id}",
        "class_name": _adapter_class_name(config.analyzer_id),
        "status": status,
    }


def _registry_with_pending_implementation(config: AnalyzerConfigIn) -> dict:
    data = _ui_to_registry(config)
    http_spec = http_spec_from_runtime_params(config.runtime_params)
    data["implementation"] = {"type": "http", **http_spec} if http_spec is not None else _implementation_metadata(config)
    return data


def _comment_safe(text: str) -> str:
    """User text for a docstring or comment in generated code: one line, and no quote or backslash
    that could end the docstring and turn the rest into code that runs when the adapter is imported."""
    return " ".join(text.replace('"', "'").replace("\\", "/").split())


def _adapter_stub_text(config: AnalyzerConfigIn) -> str:
    class_name = _adapter_class_name(config.analyzer_id)
    display_name = _comment_safe(config.display_name)
    library = _comment_safe(config.library)
    return f'''from __future__ import annotations

import pandas as pd

from intelligence.analyzers.base import Analyzer
from intelligence.capability import Capability
from intelligence.signals.schema import OperationalSignal


class {class_name}(Analyzer):
    """Adapter stub for {display_name}.

    Input:
        dataframe: normalized time-series rows with timestamp, value, metric_name,
        service, and env columns.

    Output:
        A list of OperationalSignal objects. Return an empty list when the
        analyzer does not find meaningful behavior.
    """

    analyzer_id = "{config.analyzer_id}"

    def __init__(self, **config: object) -> None:
        self.config = config

    def capability(self) -> Capability:
        return Capability(
            id="{config.analyzer_id}",
            title={config.display_name!r},
            description="Custom analyzer adapter. Implement analyze() before enabling execution.",
            analyzer_id=self.analyzer_id,
            enabled=True,
            supported_question_ids=["what_changed", "service_health", "investigation_priority"],
        )

    def analyze(self, dataframe: pd.DataFrame) -> list[OperationalSignal]:
        # TODO: Call {library} or your API/model here.
        # Expected dataframe columns:
        #   timestamp, value, metric_name, service, env
        #
        # Return OperationalSignal objects, for example:
        #   OperationalSignal(
        #       signal_type="forecast",
        #       analyzer_id=self.analyzer_id,
        #       metric_name=str(dataframe.iloc[0]["metric_name"]),
        #       service=dataframe.iloc[0].get("service"),
        #       env=dataframe.iloc[0].get("env"),
        #       severity="medium",
        #       confidence=0.8,
        #       start_time=dataframe["timestamp"].min().to_pydatetime(),
        #       end_time=dataframe["timestamp"].max().to_pydatetime(),
        #       summary="Describe what the analyzer found.",
        #       evidence={{"library": "{library}"}},
        #   )
        return []
'''


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
    executable_ids = _executable_analyzer_ids()
    # "not_implemented" is the sentinel a self-implemented custom analyzer's runtime_mapping
    # carries (see _config_to_registration_dict - it always points class_path at the analyzer's
    # own id, ignoring runtime_mapping). Checking analyzer_id directly first means a genuinely
    # backend-supported custom analyzer is recognized as executable even though its own
    # runtime_mapping field is still the "not_implemented" sentinel, not a real builtin id.
    backend_implementation_exists = analyzer_id in executable_ids or executable_mapping in executable_ids
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
    # _validate_analyzer above already raised if this config were structurally invalid, so
    # reaching this point means it's already validated - there used to be a separate
    # "Validate Rules" step/endpoint after this one that did nothing but flip this same status
    # unconditionally (see git history: mark_routing_tested). Landing directly on
    # "routing_tested" here means Promote is available right after Save, with one less click
    # that never actually checked anything additional.
    routing_test_json = {"status": "passed", "message": "Structural validation passed when the draft was saved."}
    if existing is None:
        row = AnalyzerDraftEntity(
            analyzer_id=payload.config.analyzer_id,
            display_name=payload.config.display_name,
            status="routing_tested",
            config_json=payload.config.model_dump(),
            readiness_json=readiness,
            routing_test_json=routing_test_json,
            created_by=payload.created_by,
            updated_at=now,
        )
        db.add(row)
    else:
        row = existing
        row.display_name = payload.config.display_name
        row.config_json = payload.config.model_dump()
        row.readiness_json = readiness
        row.routing_test_json = routing_test_json
        row.status = "routing_tested" if row.status not in {"executable", "benchmark_passed"} else row.status
        row.updated_at = now
    db.commit()
    db.refresh(row)
    return _draft_to_out(row)


@router.post("/drafts/{draft_id}/promote", response_model=AnalyzerDraftOut, dependencies=[Depends(require_file_writes)])
def promote_analyzer_draft(draft_id: int, db: Session = Depends(get_db)) -> AnalyzerDraftOut:
    """Registers the draft with the real pipeline and router by writing
    config/analyzer_registry.d/custom_{analyzer_id}.yml (see intelligence/analyzer_registry.py
    and the additive merge in experiments/analyzer_router/analyzer_registry.py). This is what
    makes the analyzer real - construction and routing both read from this directory now, not
    the old config/custom_analyzers.yaml file that nothing outside this API ever read.

    class_path is written pointing at the adapter stub location even though the stub file may
    not exist yet (that happens in add_backend_support below) - if something tries to actually
    construct this analyzer before the stub exists, instantiate() raises a clear import error
    that SignalPipeline._build_analyzers() already catches and skips, same as any other
    misconfigured analyzer. Nothing crashes; it's simply not executable until the stub is there.
    """
    row = db.get(AnalyzerDraftEntity, draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Analyzer draft not found")
    config = AnalyzerConfigIn(**(row.config_json or {}))
    _validate_analyzer(config)
    CUSTOM_ANALYZER_REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    _write_yaml(
        _custom_registration_path(config.analyzer_id),
        {"analyzers": {config.analyzer_id: _config_to_registration_dict(config)}},
    )
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


@router.post("/drafts/{draft_id}/backend-support", response_model=BackendSupportOut, dependencies=[Depends(require_file_writes)])
def add_backend_support(draft_id: int, db: Session = Depends(get_db)) -> BackendSupportOut:
    row = db.get(AnalyzerDraftEntity, draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Analyzer draft not found")
    if row.promoted_at is None:
        raise HTTPException(status_code=400, detail="Promote the analyzer before adding backend execution support.")

    config = AnalyzerConfigIn(**(row.config_json or {}))
    _validate_analyzer(config)
    if http_spec_from_runtime_params(config.runtime_params) is not None:
        raise HTTPException(
            status_code=400,
            detail="An External API / Model analyzer doesn't need a Python adapter - it runs by calling its Analyze URL.",
        )

    registration_path = _custom_registration_path(config.analyzer_id)
    if not registration_path.exists():
        raise HTTPException(status_code=404, detail="Promoted custom analyzer registration not found. Promote it first.")
    # Re-write to keep the registration in sync with the current draft config (e.g. if it changed
    # since promote) - class_path is already correct from promote, this just refreshes the rest.
    _write_yaml(
        registration_path,
        {"analyzers": {config.analyzer_id: _config_to_registration_dict(config)}},
    )
    implementation = _implementation_metadata(config, status="pending")

    CUSTOM_ANALYZER_ADAPTER_DIR.mkdir(parents=True, exist_ok=True)
    init_path = CUSTOM_ANALYZER_ADAPTER_DIR / "__init__.py"
    init_created = False
    if not init_path.exists():
        init_path.write_text("", encoding="utf-8")
        init_created = True

    adapter_path = CUSTOM_ANALYZER_ADAPTER_DIR / f"{config.analyzer_id}.py"
    created = False
    if not adapter_path.exists():
        adapter_path.write_text(_adapter_stub_text(config), encoding="utf-8")
        created = True

    row.readiness_json = get_analyzer_readiness(
        analyzer_id=config.analyzer_id,
        library=config.library,
        import_name=config.library,
        runtime_mapping=config.runtime_mapping,
    ).model_dump()
    row.updated_at = datetime.utcnow()
    db.commit()

    status_detail = "created" if created else "already existed"
    if init_created:
        status_detail += "; package __init__.py created"
    return BackendSupportOut(
        analyzer_id=config.analyzer_id,
        implementation_status="pending",
        module=implementation["module"],
        class_name=implementation["class_name"],
        adapter_path=str(adapter_path),
        created=created,
        message=f"Backend adapter stub {status_detail}. Implementation status is pending until the adapter is completed and verified.",
    )


@router.get("/drafts/{draft_id}/yaml-preview", response_model=AnalyzerDraftYamlPreviewOut)
def preview_analyzer_draft_yaml(draft_id: int, db: Session = Depends(get_db)) -> AnalyzerDraftYamlPreviewOut:
    row = db.get(AnalyzerDraftEntity, draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Analyzer draft not found")
    config = AnalyzerConfigIn(**(row.config_json or {}))
    _validate_analyzer(config)
    return AnalyzerDraftYamlPreviewOut(analyzer_id=config.analyzer_id, yaml_text=_draft_yaml_text(config))


@router.get("/drafts/{draft_id}/adapter-source", response_model=AdapterSourceOut)
def get_adapter_source(draft_id: int, db: Session = Depends(get_db)) -> AdapterSourceOut:
    """Shows the generated adapter file's current contents right in the wizard, so implementing
    analyze() doesn't require leaving the browser to go find the file - refetch after editing to
    see your own changes reflected here."""
    row = db.get(AnalyzerDraftEntity, draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Analyzer draft not found")
    config = AnalyzerConfigIn(**(row.config_json or {}))
    adapter_path = _custom_adapter_path(config.analyzer_id)
    if not adapter_path.exists():
        raise HTTPException(status_code=404, detail="Adapter file not found. Add backend support first.")
    return AdapterSourceOut(
        analyzer_id=config.analyzer_id,
        adapter_path=str(adapter_path),
        source=adapter_path.read_text(encoding="utf-8"),
    )


@router.post("/drafts/{draft_id}/execution-test", response_model=ExecutionTestOut)
def run_execution_test(draft_id: int, payload: ExecutionTestIn = Body(default=ExecutionTestIn()), db: Session = Depends(get_db)) -> ExecutionTestOut:
    row = db.get(AnalyzerDraftEntity, draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Analyzer draft not found")
    config = AnalyzerConfigIn(**(row.config_json or {}))
    runtime_mapping = _resolve_runtime_mapping(config.runtime_mapping, config.analyzer_id)
    registration = _custom_registration_for(config.analyzer_id)
    is_http = registration is not None and registration.http is not None
    has_own_adapter = registration is not None and (is_http or _custom_adapter_path(config.analyzer_id).exists())

    if has_own_adapter:
        # A genuinely new analyzer (Promote + Add backend support already run) - construct it
        # for real via the same loader/instantiate() the production pipeline uses, and call its
        # own analyze() directly, instead of routing through the CSV pipeline machinery built
        # around the 7 static built-in ids.
        #
        # If a real sample was picked (payload.analysis_run_id), use its actual normalized
        # points - already-normalized rows from a real ingestion run, queried as-is - instead of
        # a synthetic ramp. A clean run against synthetic data only proves "the code doesn't
        # crash"; running against real history proves it actually catches (or doesn't catch)
        # the pattern it was written for.
        data_source: Literal["real", "synthetic"] = "synthetic"
        if payload.analysis_run_id:
            query = select(NormalizedPoint).where(run_points_filter(db, payload.analysis_run_id))
            if payload.service:
                query = query.where(NormalizedPoint.service == payload.service)
            points = db.execute(query.order_by(NormalizedPoint.timestamp)).scalars().all()
            if not points:
                return ExecutionTestOut(
                    analyzer_id=config.analyzer_id,
                    available=True,
                    status="failed",
                    reason=f"No normalized points found for analysis_run_id '{payload.analysis_run_id}'.",
                    runtime_mapping=config.runtime_mapping,
                    data_source="real",
                )
            normalized = pd.DataFrame(
                [
                    {
                        "timestamp": point.timestamp,
                        "value": point.value,
                        "metric_name": point.metric_name,
                        "service": point.service,
                        "env": point.env,
                    }
                    for point in points
                ]
            )
            data_source = "real"
        else:
            sample_count = max(config.min_samples, 90)
            timestamps = pd.date_range(end=pd.Timestamp.utcnow(), periods=sample_count, freq="5min")
            raw = pd.DataFrame(
                {
                    "timestamp": timestamps,
                    "value": [50.0 + (idx * 0.08) for idx in range(sample_count)],
                    "metric_name": f"{config.analyzer_id}_execution_test",
                    "service": "execution-test",
                }
            )
            input_config = InputConfig(
                source_type="csv",
                file_path="",
                history="1d",
                interval="5m",
                timestamp_column="timestamp",
                value_column="value",
                metric_column="metric_name",
                required_columns=["timestamp", "metric_name", "value"],
                optional_columns=["service", "env", "host", "namespace", "pod", "source", "unit", "metric_type"],
                service="execution-test",
                metric_name=f"{config.analyzer_id}_execution_test",
            )
            normalized = normalize_timeseries(raw, input_config)

        try:
            analyzer_instance = instantiate_analyzer(registration, overrides=config.runtime_params or {})
            if is_http:
                health_issue = analyzer_instance.check_health()
                if health_issue:
                    raise RuntimeError(health_issue)
            with analyzer_slot(analyzer_instance):
                signals = analyzer_instance.analyze(normalized)
            ran = (
                f"called {safe_url(registration.http.analyze_url)}"
                if is_http
                else "ran your analyzer's own analyze()"
            )
            result = ExecutionTestOut(
                analyzer_id=config.analyzer_id,
                available=True,
                status="passed",
                reason=f"Execution test passed - {ran} directly against {data_source} data.",
                runtime_mapping=config.runtime_mapping,
                sample_count=len(normalized),
                signal_count=len(signals),
                finding_count=0,
                data_source=data_source,
            )
        except Exception as exc:  # pragma: no cover - custom analyzer code varies
            result = ExecutionTestOut(
                analyzer_id=config.analyzer_id,
                available=True,
                status="failed",
                reason=f"Execution test failed: {exc}",
                runtime_mapping=config.runtime_mapping,
                sample_count=len(normalized),
                data_source=data_source,
            )
        row.execution_test_json = result.model_dump()
        row.updated_at = datetime.utcnow()
        db.commit()
        return result

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


@router.delete("/analyzers/{analyzer_id}", response_model=dict, dependencies=[Depends(require_file_writes)])
def delete_analyzer_completely(
    analyzer_id: str,
    delete_code_file: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    """Deletes everything this wizard created for one analyzer, in one action, regardless of
    which stage it's at - a draft still in Postgres, a promoted registration, or a fully
    backend-supported one. Replaces the old split delete (a drafts-only endpoint plus
    admin_analyzers.py's registry-only endpoint) that left orphaned rows behind: deleting only
    the registry file used to leave the Postgres draft invisible but still marked
    'executable', so re-saving the same analyzer_id later silently inherited that stale status
    instead of starting over as an unverified draft.

    delete_code_file defaults to false - keeping the generated Python file is the safer default
    if you're planning to fix and re-promote under the same id; pass true for a clean slate.
    """
    if analyzer_id in EXECUTABLE_ANALYZER_IDS:
        raise HTTPException(status_code=400, detail="Built-in analyzers cannot be deleted.")

    deleted = {"draft": False, "registration": False, "code_file": False}

    draft_row = db.execute(
        select(AnalyzerDraftEntity).where(AnalyzerDraftEntity.analyzer_id == analyzer_id)
    ).scalar_one_or_none()
    if draft_row is not None:
        db.delete(draft_row)
        db.commit()
        deleted["draft"] = True

    registration_path = _custom_registration_path(analyzer_id)
    if registration_path.exists():
        registration_path.unlink()
        deleted["registration"] = True

    if delete_code_file:
        adapter_path = _custom_adapter_path(analyzer_id)
        if adapter_path.exists():
            adapter_path.unlink()
            deleted["code_file"] = True

    if not any(deleted.values()):
        raise HTTPException(status_code=404, detail="Nothing found to delete for this analyzer_id.")
    return {"analyzer_id": analyzer_id, **deleted}


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
