from __future__ import annotations

import importlib
import importlib.util
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from intelligence.analyzers.base import Analyzer
from intelligence.config import deep_merge

logger = logging.getLogger(__name__)

# Same metric/operator vocabulary the router scoring rules already support (see
# backend/app/api/admin_analyzers.py) - kept in sync so a registration written for one surface
# validates the same way everywhere.
SUPPORTED_PROFILE_METRICS = {
    "sample_count",
    "regular_sampling",
    "seasonality_strength",
    "trend_strength",
    "shift_index",
    "spikiness",
    "missing_percentage",
    "irregular_sampling_percentage",
    "constant_value_percentage",
    "calendar_seasonality_strength",
    "behavior_mix",
}
SUPPORTED_OPERATORS = {"gte", "gt", "lte", "lt", "equals"}


class AnalyzerRegistrationError(ValueError):
    """Raised by instantiate() when a registration cannot be turned into a real Analyzer."""


@dataclass(slots=True)
class HttpAnalyzerSpec:
    """Declares an analyzer implemented as an external HTTP service rather than a Python class.
    instantiate() turns it into an HttpAnalyzer (intelligence/analyzers/http_analyzer.py); the
    request and reply format is in docs/http-analyzer-contract.md. Prefer api_key_env (the name of
    an environment variable holding the key) over api_key, so the key stays out of the YAML."""

    analyze_url: str
    health_check_url: str | None = None
    timeout_seconds: float = 30.0
    api_key: str | None = None
    api_key_env: str | None = None


@dataclass(slots=True)
class RouterSpec:
    """The router-facing half of a registration: what data shapes this analyzer is good for,
    and how the router should score it. Mirrors AnalyzerCapability's fields in
    experiments/analyzer_router/analyzer_registry.py so the two can eventually merge."""

    supported_profiles: list[str] = field(default_factory=list)
    eligibility_rules: dict[str, Any] = field(default_factory=dict)
    scoring_rules: dict[str, Any] = field(default_factory=dict)
    explanation_templates: dict[str, str] = field(default_factory=dict)
    # Router ids (e.g. "trend_regression") that should resolve to this analyzer_id at runtime -
    # the data-driven replacement for SignalPipeline._router_to_pipeline_analyzers's hardcoded dict.
    router_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AnalyzerRegistration:
    analyzer_id: str
    display_name: str
    enabled: bool
    source_file: str
    class_path: str | None
    http: HttpAnalyzerSpec | None
    router: RouterSpec
    runtime_params: dict[str, Any] = field(default_factory=dict)
    # Runs on every analysis the router doesn't REJECT it for, outside the max_analyzers /
    # min_score contest - for cheap guard-style analyzers (e.g. a data-health check) that must
    # never lose a slot to a higher-scoring shape analyzer.
    always_run: bool = False
    # An optional library the analyzer's method needs (e.g. "prophet"). Without it the analyzer
    # runs a simpler fallback, not the method the router scored, so it may not take one of the
    # router's max_analyzers slots (it still runs when every analyzer is asked for).
    requires_library: str | None = None
    # One or two plain sentences on what the analyzer looks for, with an example. Shown as a tip
    # next to the analyzer's name in the web UI and the Grafana plugin.
    description: str | None = None


def _validate_entry(analyzer_id: str, data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not analyzer_id or not analyzer_id[0].isalpha():
        errors.append("analyzer id must start with a letter")

    class_path = data.get("class_path")
    http = data.get("http")
    if not class_path and not http:
        errors.append("must declare either class_path or http")
    if class_path and http:
        errors.append("must declare only one of class_path or http, not both")
    if http is not None and not isinstance(http, dict):
        errors.append("http must be a mapping")
    elif isinstance(http, dict):
        if not http.get("analyze_url"):
            errors.append("http block must declare analyze_url")
        for url_key in ("analyze_url", "health_check_url"):
            url = http.get(url_key)
            if url and not str(url).lower().startswith(("http://", "https://")):
                errors.append(f"http {url_key} must start with http:// or https://")

    router = data.get("router") or {}
    if not isinstance(router, dict):
        errors.append("router must be a mapping")
        router = {}
    scoring_rules = (router.get("scoring_rules") or {})
    for rule in scoring_rules.get("rules", []) if isinstance(scoring_rules, dict) else []:
        if not isinstance(rule, dict):
            errors.append("every scoring rule must be a mapping")
            continue
        metric = rule.get("metric")
        if metric not in SUPPORTED_PROFILE_METRICS:
            errors.append(f"scoring rule references unknown metric '{metric}'")
        operators_present = [op for op in SUPPORTED_OPERATORS if op in rule]
        if len(operators_present) != 1:
            errors.append(f"scoring rule must declare exactly one operator from {sorted(SUPPORTED_OPERATORS)}")

    return errors


def _parse_entry(analyzer_id: str, data: dict[str, Any], source_file: str) -> AnalyzerRegistration:
    router_data = data.get("router") or {}
    http_data = data.get("http")
    return AnalyzerRegistration(
        analyzer_id=analyzer_id,
        display_name=str(data.get("display_name", analyzer_id)),
        enabled=bool(data.get("enabled", True)),
        source_file=source_file,
        class_path=data.get("class_path"),
        http=(
            HttpAnalyzerSpec(
                analyze_url=str(http_data["analyze_url"]),
                health_check_url=http_data.get("health_check_url"),
                timeout_seconds=float(http_data.get("timeout_seconds", 30.0)),
                api_key=http_data.get("api_key"),
                api_key_env=http_data.get("api_key_env"),
            )
            if http_data
            else None
        ),
        router=RouterSpec(
            supported_profiles=list(router_data.get("supported_profiles", [])),
            eligibility_rules=dict(router_data.get("eligibility_rules") or {}),
            scoring_rules=dict(router_data.get("scoring_rules") or {}),
            explanation_templates=dict(router_data.get("explanation_templates") or {}),
            router_ids=list(router_data.get("router_ids", [])),
        ),
        runtime_params=dict(data.get("runtime_params") or {}),
        always_run=bool(data.get("always_run", False)),
        requires_library=data.get("requires_library"),
        description=str(data.get("description") or "").strip() or None,
    )


def library_installed(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def missing_libraries(config_path: str | Path) -> dict[str, str]:
    """Analyzer id -> the optional library it declares (requires_library) that isn't installed."""
    return {
        registration.analyzer_id: registration.requires_library
        for registration in load_registrations(config_path)
        if registration.requires_library and not library_installed(registration.requires_library)
    }


def load_registrations(config_path: str | Path, *, validate: bool = True) -> list[AnalyzerRegistration]:
    """Loads analyzer registrations from a single YAML file or every *.yml/*.yaml file in a
    directory - same directory-of-files, skip-and-log posture as
    backend/app/behavior_intelligence/loader.py, so one bad file or one bad entry doesn't take
    the rest of the app down. Duplicate analyzer_id across files keeps the first one loaded."""
    path = Path(config_path)
    if path.is_dir():
        files = sorted(list(path.glob("*.yml")) + list(path.glob("*.yaml")))
    elif path.exists():
        files = [path]
    else:
        files = []

    seen_ids: dict[str, str] = {}
    registrations: list[AnalyzerRegistration] = []
    for file_path in files:
        try:
            raw = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            logger.warning("Skipping analyzer registry file %s: invalid YAML (%s)", file_path, exc)
            continue
        if not isinstance(raw, dict):
            logger.warning("Skipping analyzer registry file %s: top level must be a mapping", file_path)
            continue

        analyzers = raw.get("analyzers") or {}
        if not isinstance(analyzers, dict):
            logger.warning("Skipping analyzer registry file %s: 'analyzers' must be a mapping", file_path)
            continue

        for analyzer_id, data in analyzers.items():
            if not isinstance(data, dict):
                logger.warning("Skipping analyzer '%s' in %s: entry must be a mapping", analyzer_id, file_path)
                continue
            if analyzer_id in seen_ids:
                logger.warning(
                    "Skipping duplicate analyzer id '%s' in %s (already loaded from %s)",
                    analyzer_id,
                    file_path.name,
                    seen_ids[analyzer_id],
                )
                continue
            if validate:
                errors = _validate_entry(analyzer_id, data)
                if errors:
                    logger.warning(
                        "Skipping analyzer '%s' in %s: %s", analyzer_id, file_path.name, "; ".join(errors)
                    )
                    continue
            try:
                registration = _parse_entry(analyzer_id, data, file_path.name)
            except Exception as exc:  # malformed nested fields (e.g. bad http block types)
                logger.warning("Skipping analyzer '%s' in %s: %s", analyzer_id, file_path.name, exc)
                continue
            seen_ids[analyzer_id] = file_path.name
            registrations.append(registration)

    return registrations


def instantiate(registration: AnalyzerRegistration, overrides: dict[str, Any] | None = None) -> Analyzer:
    """Constructs the real Analyzer for a registration by dynamically importing class_path.
    Raises AnalyzerRegistrationError on any failure - callers decide whether to isolate/log a
    single bad analyzer rather than let it take the whole pipeline run down (same per-analyzer
    isolation posture already used elsewhere in the pipeline).

    HTTP-backed registrations (registration.http set) become an HttpAnalyzer, which only calls the
    service when analyze() runs - constructing one never touches the network.
    """
    if registration.http is not None:
        from intelligence.analyzers.http_analyzer import HttpAnalyzer

        return HttpAnalyzer(
            analyzer_id=registration.analyzer_id,
            spec=registration.http,
            params=deep_merge(registration.runtime_params, overrides or {}),
            display_name=registration.display_name,
        )
    if not registration.class_path:
        raise AnalyzerRegistrationError(f"analyzer '{registration.analyzer_id}' declares neither class_path nor http")

    module_name, _, class_name = registration.class_path.rpartition(".")
    if not module_name or not class_name:
        raise AnalyzerRegistrationError(
            f"analyzer '{registration.analyzer_id}': class_path '{registration.class_path}' "
            "must be in 'package.module.ClassName' form"
        )

    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise AnalyzerRegistrationError(
            f"analyzer '{registration.analyzer_id}': could not import module '{module_name}': {exc}"
        ) from exc

    analyzer_class = getattr(module, class_name, None)
    if analyzer_class is None:
        raise AnalyzerRegistrationError(
            f"analyzer '{registration.analyzer_id}': class '{class_name}' not found in module '{module_name}'"
        )
    if not (isinstance(analyzer_class, type) and issubclass(analyzer_class, Analyzer)):
        raise AnalyzerRegistrationError(
            f"analyzer '{registration.analyzer_id}': '{registration.class_path}' is not an Analyzer subclass"
        )

    # Key by key: an override of finding_rules.min_slope_percent keeps the rest of finding_rules.
    params = deep_merge(registration.runtime_params, overrides or {})
    try:
        instance = analyzer_class(**params)
    except TypeError as exc:
        raise AnalyzerRegistrationError(
            f"analyzer '{registration.analyzer_id}': failed to construct '{registration.class_path}' "
            f"with runtime_params {sorted(params)}: {exc}"
        ) from exc

    if instance.analyzer_id != registration.analyzer_id:
        logger.warning(
            "Analyzer registered as '%s' constructed an instance whose analyzer_id is '%s' - "
            "these should match, downstream code keys off analyzer_id.",
            registration.analyzer_id,
            instance.analyzer_id,
        )
    return instance
