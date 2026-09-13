from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from experiments.analyzer_router.analyzer_registry import AnalyzerRegistry
from experiments.analyzer_router.models import SeriesProfile
from experiments.analyzer_router.router import UniversalTimeSeriesRouter
from intelligence.analyzer_registry import AnalyzerRegistration, load_registrations


router = APIRouter(prefix="/api/admin/analyzers", tags=["admin-analyzers"])

REGISTRY_PATH = Path("experiments/analyzer_router/analyzer_registry.yaml")
CUSTOM_ANALYZERS_PATH = Path("config/custom_analyzers.yaml")
# Where backend/app/api/analyzer_labs.py's Promote/Add backend support actually write now (see
# that module's CUSTOM_ANALYZER_REGISTRY_DIR/CUSTOM_ANALYZER_ADAPTER_DIR) - duplicated here as
# plain Path constants rather than imported, to avoid a circular import (analyzer_labs.py already
# imports several helpers from this module).
CUSTOM_ANALYZER_REGISTRY_DIR = Path("config/analyzer_registry.d")
CUSTOM_ANALYZER_ADAPTER_DIR = Path("backend/app/analyzers/custom")
SUPPORTED_PROFILE_METRICS = {
    "sample_count",
    "regular_sampling",
    "seasonality_strength",
    "trend_strength",
    "shift_index",
    "spikiness",
    "missing_percentage",
    "irregular_sampling_percentage",
    "behavior_mix",
}
SUPPORTED_OPERATORS = {"gte", "gt", "lte", "lt", "equals"}


class ScoringRuleIn(BaseModel):
    metric: str
    operator: Literal["gte", "gt", "lte", "lt", "equals"]
    threshold: float | bool
    add: float


class AnalyzerConfigIn(BaseModel):
    analyzer_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str
    template_type: str
    library: str
    enabled: bool = True
    runtime_mapping: str = "not_implemented"
    supported_profiles: list[str]
    min_samples: int = 30
    requires_regular_sampling: bool = False
    requires_numeric: bool = True
    base_score: float = 0.3
    scoring_rules: list[ScoringRuleIn]
    runtime_params: dict[str, Any] = Field(default_factory=dict)
    selected_explanation: str
    excluded_explanation: str


class AnalyzerConfigOut(AnalyzerConfigIn):
    source: Literal["builtin", "custom"]
    routable: bool
    executable: bool
    implementation_status: str | None = None
    implementation_module: str | None = None
    implementation_class_name: str | None = None


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False)


def _registry_rule_to_ui(rule: dict[str, Any]) -> ScoringRuleIn:
    for operator in SUPPORTED_OPERATORS:
        if operator in rule:
            return ScoringRuleIn(
                metric=str(rule["metric"]),
                operator=operator,  # type: ignore[arg-type]
                threshold=rule[operator],
                add=float(rule.get("add", 0.0)),
            )
    return ScoringRuleIn(metric=str(rule.get("metric", "")), operator="gte", threshold=0.0, add=float(rule.get("add", 0.0)))


def _registry_analyzer_to_ui(analyzer_id: str, data: dict[str, Any], source: Literal["builtin", "custom"]) -> AnalyzerConfigOut:
    eligibility = data.get("eligibility_rules") or {}
    scoring = data.get("scoring_rules") or {}
    metadata = data.get("admin_metadata") or {}
    implementation = data.get("implementation") or {}
    if not isinstance(implementation, dict):
        implementation = {}
    runtime_mapping = str(metadata.get("runtime_mapping") or ("not_implemented" if source == "custom" else analyzer_id))
    return AnalyzerConfigOut(
        analyzer_id=analyzer_id,
        display_name=str(data.get("display_name", analyzer_id)),
        template_type=str(metadata.get("template_type", "Custom")),
        library=str(metadata.get("library", analyzer_id)),
        enabled=bool(metadata.get("enabled", True)),
        runtime_mapping=runtime_mapping,
        supported_profiles=list(data.get("supported_profiles") or []),
        min_samples=int(eligibility.get("min_samples", 30)),
        requires_regular_sampling=bool(eligibility.get("requires_regular_sampling", False)),
        requires_numeric=bool(eligibility.get("requires_numeric", True)),
        base_score=float(scoring.get("base", 0.3)),
        scoring_rules=[_registry_rule_to_ui(rule) for rule in scoring.get("rules", [])],
        runtime_params=dict(metadata.get("runtime_params") or {}),
        selected_explanation=str((data.get("explanation_templates") or {}).get("selected", "")),
        excluded_explanation=str((data.get("explanation_templates") or {}).get("excluded", "")),
        source=source,
        routable=True,
        executable=runtime_mapping != "not_implemented",
        implementation_status=str(implementation.get("status")) if implementation.get("status") else None,
        implementation_module=str(implementation.get("module")) if implementation.get("module") else None,
        implementation_class_name=str(implementation.get("class_name")) if implementation.get("class_name") else None,
    )


def _ui_to_registry(data: AnalyzerConfigIn) -> dict[str, Any]:
    return {
        "display_name": data.display_name,
        "supported_profiles": data.supported_profiles,
        "eligibility_rules": {
            "min_samples": data.min_samples,
            "requires_numeric": data.requires_numeric,
            **({"requires_regular_sampling": True} if data.requires_regular_sampling else {}),
        },
        "suitability_rules": {},
        "scoring_rules": {
            "base": data.base_score,
            "rules": [
                {"metric": rule.metric, rule.operator: rule.threshold, "add": rule.add}
                for rule in data.scoring_rules
            ],
        },
        "explanation_templates": {
            "selected": data.selected_explanation,
            "excluded": data.excluded_explanation,
        },
        "admin_metadata": {
            "template_type": data.template_type,
            "library": data.library,
            "enabled": data.enabled,
            "runtime_mapping": data.runtime_mapping,
            "runtime_params": data.runtime_params,
        },
    }


def _validate_analyzer(data: AnalyzerConfigIn) -> None:
    if not data.supported_profiles:
        raise HTTPException(status_code=422, detail="At least one supported profile is required.")
    if not data.scoring_rules:
        raise HTTPException(status_code=422, detail="At least one scoring rule is required.")
    for rule in data.scoring_rules:
        if rule.metric not in SUPPORTED_PROFILE_METRICS:
            raise HTTPException(status_code=422, detail=f"Unsupported profile metric: {rule.metric}")
        if rule.operator not in SUPPORTED_OPERATORS:
            raise HTTPException(status_code=422, detail=f"Unsupported operator: {rule.operator}")


def _merged_registry() -> dict[str, Any]:
    builtin = _read_yaml(REGISTRY_PATH)
    custom = _read_yaml(CUSTOM_ANALYZERS_PATH)
    merged = {"registry_version": "admin", "analyzers": {}}
    merged["analyzers"].update(builtin.get("analyzers", {}))
    merged["analyzers"].update(custom.get("analyzers", {}))
    return merged


def _new_registration_to_ui(registration: AnalyzerRegistration) -> AnalyzerConfigOut:
    """Converts a config/analyzer_registry.d/ registration (the real, connected location
    analyzer_labs.py's Promote/Add backend support write to) into the same AnalyzerConfigOut
    shape _registry_analyzer_to_ui produces for the legacy custom_analyzers.yaml, so both sources
    show up together in this list instead of a newly-promoted analyzer silently not appearing
    here even though it's genuinely live."""
    adapter_exists = (CUSTOM_ANALYZER_ADAPTER_DIR / f"{registration.analyzer_id}.py").exists()
    module, _, class_name = (registration.class_path or "").rpartition(".")
    return AnalyzerConfigOut(
        analyzer_id=registration.analyzer_id,
        display_name=registration.display_name,
        template_type="Custom",
        library=registration.analyzer_id,
        enabled=registration.enabled,
        runtime_mapping=registration.analyzer_id if registration.class_path else "not_implemented",
        supported_profiles=list(registration.router.supported_profiles),
        min_samples=int(registration.router.eligibility_rules.get("min_samples", 30)),
        requires_regular_sampling=bool(registration.router.eligibility_rules.get("requires_regular_sampling", False)),
        requires_numeric=bool(registration.router.eligibility_rules.get("requires_numeric", True)),
        base_score=float(registration.router.scoring_rules.get("base", 0.3)),
        scoring_rules=[_registry_rule_to_ui(rule) for rule in registration.router.scoring_rules.get("rules", [])],
        runtime_params=dict(registration.runtime_params),
        selected_explanation=str(registration.router.explanation_templates.get("selected", "")),
        excluded_explanation=str(registration.router.explanation_templates.get("excluded", "")),
        source="custom",
        routable=True,
        executable=adapter_exists,
        implementation_status="verified" if adapter_exists else "pending",
        implementation_module=module or None,
        implementation_class_name=class_name or None,
    )


def _load_new_custom_registrations() -> list[AnalyzerRegistration]:
    """Everything in config/analyzer_registry.d/ except builtin.yml - that file holds the 7 real
    built-in analyzers (migrated there from the old hardcoded pipeline construction; see
    intelligence/pipeline.py), which this "Promoted Custom Analyzers" list should never show
    alongside things a user actually promoted through the wizard."""
    if not CUSTOM_ANALYZER_REGISTRY_DIR.exists():
        return []
    return [reg for reg in load_registrations(CUSTOM_ANALYZER_REGISTRY_DIR) if reg.source_file != "builtin.yml"]


@router.get("")
def list_analyzers() -> list[AnalyzerConfigOut]:
    builtin = _read_yaml(REGISTRY_PATH).get("analyzers", {})
    custom = _read_yaml(CUSTOM_ANALYZERS_PATH).get("analyzers", {})
    items = [
        _registry_analyzer_to_ui(analyzer_id, data, "builtin")
        for analyzer_id, data in builtin.items()
    ]
    items.extend(
        _registry_analyzer_to_ui(analyzer_id, data, "custom")
        for analyzer_id, data in custom.items()
    )
    items.extend(_new_registration_to_ui(registration) for registration in _load_new_custom_registrations())
    return sorted(items, key=lambda item: (item.source, item.analyzer_id))


@router.post("/validate")
def validate_analyzer(data: AnalyzerConfigIn) -> dict[str, str]:
    _validate_analyzer(data)
    return {"status": "valid"}


@router.post("")
def save_analyzer(data: AnalyzerConfigIn) -> AnalyzerConfigOut:
    _validate_analyzer(data)
    custom = _read_yaml(CUSTOM_ANALYZERS_PATH)
    analyzers = custom.setdefault("analyzers", {})
    analyzers[data.analyzer_id] = _ui_to_registry(data)
    _write_yaml(CUSTOM_ANALYZERS_PATH, custom)
    return _registry_analyzer_to_ui(data.analyzer_id, analyzers[data.analyzer_id], "custom")


@router.delete("/{analyzer_id}")
def delete_custom_analyzer(analyzer_id: str) -> dict[str, Any]:
    new_registration_path = CUSTOM_ANALYZER_REGISTRY_DIR / f"custom_{analyzer_id}.yml"
    if new_registration_path.exists():
        new_registration_path.unlink()
        return {"deleted": 1, "analyzer_id": analyzer_id}

    custom = _read_yaml(CUSTOM_ANALYZERS_PATH)
    custom_analyzers = custom.get("analyzers", {})
    if not isinstance(custom_analyzers, dict) or analyzer_id not in custom_analyzers:
        builtin_analyzers = _read_yaml(REGISTRY_PATH).get("analyzers", {})
        if isinstance(builtin_analyzers, dict) and analyzer_id in builtin_analyzers:
            raise HTTPException(status_code=400, detail="Built-in analyzers cannot be removed from custom config.")
        raise HTTPException(status_code=404, detail="Custom analyzer not found.")

    del custom_analyzers[analyzer_id]
    custom["analyzers"] = custom_analyzers
    _write_yaml(CUSTOM_ANALYZERS_PATH, custom)
    return {"deleted": 1, "analyzer_id": analyzer_id}


@router.post("/test-route")
def test_route(data: AnalyzerConfigIn) -> dict[str, Any]:
    _validate_analyzer(data)
    registry_data = _merged_registry()
    registry_data["analyzers"][data.analyzer_id] = _ui_to_registry(data)
    registry = AnalyzerRegistry()
    registry.registry_version = "admin-preview"
    registry._registry = AnalyzerRegistry(config_path=REGISTRY_PATH)._load()
    temp_path = CUSTOM_ANALYZERS_PATH.parent / ".admin_preview_registry.yaml"
    _write_yaml(temp_path, registry_data)
    try:
        router_service = UniversalTimeSeriesRouter(registry_path=temp_path)
        profile = SeriesProfile(
            original_sample_count=max(data.min_samples, 80),
            valid_sample_count=max(data.min_samples, 80),
            invalid_timestamp_count=0,
            invalid_value_count=0,
            missing_percentage=0.0,
            duplicate_timestamp_count=0,
            sampling_interval_seconds=300,
            duration_seconds=300 * max(data.min_samples, 80),
            irregular_sampling_percentage=0.0,
            interpolated_sample_count=0,
            interpolated_percentage=0.0,
            constant_value_percentage=0.0,
            sample_count=max(data.min_samples, 80),
            regular_sampling=True,
            mean=50.0,
            stddev=5.0,
            minimum=30.0,
            maximum=90.0,
            variance=25.0,
            trend_slope=0.0,
            trend_strength=0.2,
            seasonality_strength=0.6,
            spikiness=0.4,
            shift_index=0.0,
            autocorrelation=None,
            trend_fit_r2=0.2,
            trend_abruptness_ratio=0.0,
            seasonality_dominant_lag=24,
            seasonality_peak_strength=0.6,
            transient_spike_count=2,
            persistent_jump_count=0,
            detected_profiles=data.supported_profiles[:],
            notes=[],
        )
        decision = next(
            decision for decision in router_service.recommend_analyzers_for_profile(profile)
            if decision.analyzer == data.analyzer_id
        )
        return {
            "analyzer_id": decision.analyzer,
            "eligible": decision.eligible,
            "recommendation": decision.recommendation,
            "final_score": decision.final_score,
            "matched_rules": decision.parameters_tested.get("matched_scoring_rules", []),
            "reasons": decision.reasons,
            "runtime_status": "executable" if data.runtime_mapping != "not_implemented" else "config_only",
        }
    finally:
        if temp_path.exists():
            temp_path.unlink()
