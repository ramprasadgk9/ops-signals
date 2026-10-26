"""Per-service analyzer settings: config/analyzer_overrides.d/*.yml.

Each file holds overrides a team owns. An override names the series it applies to (scope), why
(reason), and the analyzer settings it changes - only settings the analyzer lists as `tunable` in
config/analyzer_registry.d/, within their range:

    overrides:
      payments_memory_trend:
        scope: {service: payments-api, metric: process_resident_memory_bytes}
        reason: Memory grows slowly before an outage here; 10% is too late.
        analyzers:
          trend:
            finding_rules: {min_slope_percent: 5}
        selection: {max_analyzers: 2, disabled: [stumpy]}

The file name is for people; only `scope` decides what an override applies to. Scope values match
the series' service and metric name exactly or with wildcards (`payments-*`). A series no override
matches keeps the default settings.

A file with any problem is skipped as a whole and reported in OverrideSet.errors: one team's typo
never stops analysis or half-applies their settings.
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from intelligence.analyzer_registry import AnalyzerRegistration
from intelligence.config import deep_merge

logger = logging.getLogger(__name__)

# How a series with no service is stored. Not a service: tune those metrics with a metric scope.
NO_SERVICE_VALUES = {"unknown", "unknown-service"}
MAX_ANALYZERS_LIMIT = 10


@dataclass(slots=True)
class AnalyzerOverride:
    override_id: str
    source_file: str
    service: str | None
    metric: str | None
    reason: str
    # analyzer id -> nested settings in config/analyzers.yaml's shape.
    analyzers: dict[str, dict[str, Any]] = field(default_factory=dict)
    max_analyzers: int | None = None
    disabled: list[str] = field(default_factory=list)

    def matches(self, service: str | None, metric: str | None) -> bool:
        return _matches(self.service, service) and _matches(self.metric, metric)

    @property
    def specificity(self) -> tuple[int, int, int]:
        """Higher applies later and wins: service and metric, then service only, then metric
        only; an exact name beats a wildcard."""
        service, metric = _pattern_score(self.service), _pattern_score(self.metric)
        return (int(service > 0) + int(metric > 0), service, metric)


@dataclass(slots=True)
class OverrideLoadError:
    source_file: str
    message: str


@dataclass(slots=True)
class OverrideResolution:
    """What applies to one series: settings to merge over config/analyzers.yaml, per analyzer."""

    params: dict[str, dict[str, Any]] = field(default_factory=dict)
    max_analyzers: int | None = None
    disabled: set[str] = field(default_factory=set)
    # Override ids that applied, least specific first.
    applied: list[str] = field(default_factory=list)
    # Equally specific overrides that set the same setting differently: (setting, winner, loser).
    conflicts: list[tuple[str, str, str]] = field(default_factory=list)


@dataclass(slots=True)
class OverrideSet:
    overrides: list[AnalyzerOverride] = field(default_factory=list)
    errors: list[OverrideLoadError] = field(default_factory=list)

    def resolve(self, service: str | None, metric: str | None) -> OverrideResolution:
        resolution = OverrideResolution()
        matching = sorted(
            (override for override in self.overrides if override.matches(service, metric)),
            key=lambda override: (override.specificity, override.source_file, override.override_id),
        )
        set_by: dict[str, AnalyzerOverride] = {}
        for override in matching:
            for analyzer_id, settings in override.analyzers.items():
                for path, value in _leaves(settings):
                    setting = f"{analyzer_id}.{path}"
                    earlier = set_by.get(setting)
                    if earlier is not None and earlier.specificity == override.specificity and _get(resolution.params, setting) != value:
                        resolution.conflicts.append((setting, override.override_id, earlier.override_id))
                    set_by[setting] = override
                resolution.params[analyzer_id] = deep_merge(resolution.params.get(analyzer_id, {}), settings)
            if override.max_analyzers is not None:
                resolution.max_analyzers = override.max_analyzers
            resolution.disabled.update(override.disabled)
            resolution.applied.append(override.override_id)
        return resolution


def load_overrides(config_path: str | Path, registrations: list[AnalyzerRegistration]) -> OverrideSet:
    """Loads every *.yml/*.yaml file in the directory (a missing directory means no overrides)."""
    path = Path(config_path)
    files = sorted(list(path.glob("*.yml")) + list(path.glob("*.yaml"))) if path.is_dir() else []
    known = {registration.analyzer_id: registration for registration in registrations}
    result = OverrideSet()
    seen_ids: dict[str, str] = {}
    seen_scopes: dict[tuple[str | None, str | None], str] = {}
    for file_path in files:
        try:
            parsed = _parse_file(file_path, known)
        except ValueError as exc:
            result.errors.append(OverrideLoadError(file_path.name, str(exc)))
            logger.warning("Skipping analyzer overrides file %s: %s", file_path.name, exc)
            continue
        clashes = [
            f"override '{override.override_id}' is already defined in {seen_ids[override.override_id]}"
            for override in parsed
            if override.override_id in seen_ids
        ] + [
            f"override '{override.override_id}' has the same scope as '{seen_scopes[(override.service, override.metric)]}'; put both in one override"
            for override in parsed
            if (override.service, override.metric) in seen_scopes
        ]
        if clashes:
            message = "; ".join(clashes)
            result.errors.append(OverrideLoadError(file_path.name, message))
            logger.warning("Skipping analyzer overrides file %s: %s", file_path.name, message)
            continue
        for override in parsed:
            seen_ids[override.override_id] = file_path.name
            seen_scopes[(override.service, override.metric)] = override.override_id
        result.overrides.extend(parsed)
    return result


def _parse_file(file_path: Path, known: dict[str, AnalyzerRegistration]) -> list[AnalyzerOverride]:
    try:
        raw = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        # In YAML a bare value starting with * is an alias, so `service: *-api` fails to parse.
        hint = '; quote a name that starts with *, e.g. service: "*-api"' if "alias" in str(exc) else ""
        raise ValueError(f"not valid YAML ({exc}){hint}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("overrides"), dict):
        raise ValueError("the file must have an 'overrides' mapping at the top")
    overrides: list[AnalyzerOverride] = []
    scopes_here: dict[tuple[str | None, str | None], str] = {}
    for override_id, data in raw["overrides"].items():
        override = _parse_override(str(override_id), data, file_path.name, known)
        scope = (override.service, override.metric)
        if scope in scopes_here:
            raise ValueError(f"override '{override.override_id}' has the same scope as '{scopes_here[scope]}'; put both in one override")
        scopes_here[scope] = override.override_id
        overrides.append(override)
    return overrides


def _parse_override(override_id: str, data: Any, source_file: str, known: dict[str, AnalyzerRegistration]) -> AnalyzerOverride:
    def fail(message: str) -> ValueError:
        return ValueError(f"override '{override_id}': {message}")

    if not isinstance(data, dict):
        raise fail("must be a mapping")
    unknown_keys = set(data) - {"scope", "reason", "analyzers", "selection"}
    if unknown_keys:
        raise fail(f"unknown key(s) {sorted(unknown_keys)}")

    scope = data.get("scope")
    if not isinstance(scope, dict) or set(scope) - {"service", "metric"}:
        raise fail("scope must be a mapping with service and/or metric")
    service, metric = scope.get("service"), scope.get("metric")
    for name, value in (("service", service), ("metric", metric)):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise fail(f"scope.{name} must be a non-empty name")
    if service is None and metric is None:
        raise fail("scope needs a service, a metric or both")
    if service in NO_SERVICE_VALUES:
        raise fail(f"'{service}' means the metrics have no service label, not a service; scope them by metric instead")

    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise fail("reason is required: say why this service needs different settings")

    analyzers = data.get("analyzers") or {}
    if not isinstance(analyzers, dict):
        raise fail("analyzers must be a mapping of analyzer id to settings")
    for analyzer_id, settings in analyzers.items():
        registration = known.get(analyzer_id)
        if registration is None:
            raise fail(f"unknown analyzer '{analyzer_id}'")
        if not isinstance(settings, dict) or not settings:
            raise fail(f"settings for '{analyzer_id}' must be a non-empty mapping")
        for path, value in _leaves(settings):
            _check_tunable(registration, path, value, fail)

    selection = data.get("selection") or {}
    if not isinstance(selection, dict) or set(selection) - {"max_analyzers", "disabled"}:
        raise fail("selection may only set max_analyzers and disabled")
    max_analyzers = selection.get("max_analyzers")
    if max_analyzers is not None and (isinstance(max_analyzers, bool) or not isinstance(max_analyzers, int) or not 1 <= max_analyzers <= MAX_ANALYZERS_LIMIT):
        raise fail(f"selection.max_analyzers must be a whole number from 1 to {MAX_ANALYZERS_LIMIT}")
    disabled = selection.get("disabled") or []
    if not isinstance(disabled, list) or any(item not in known for item in disabled):
        raise fail(f"selection.disabled must list known analyzer ids, from {sorted(known)}")

    if not analyzers and max_analyzers is None and not disabled:
        raise fail("changes nothing: set analyzers or selection")

    return AnalyzerOverride(
        override_id=override_id,
        source_file=source_file,
        service=service.strip() if service else None,
        metric=metric.strip() if metric else None,
        reason=reason.strip(),
        analyzers={analyzer_id: dict(settings) for analyzer_id, settings in analyzers.items()},
        max_analyzers=max_analyzers,
        disabled=list(disabled),
    )


def _check_tunable(registration: AnalyzerRegistration, path: str, value: Any, fail) -> None:
    spec = registration.tunable.get(path)
    if spec is None:
        allowed = ", ".join(sorted(registration.tunable)) or "nothing"
        raise fail(f"'{registration.analyzer_id}.{path}' can't be set per service (allowed: {allowed})")
    kind = spec["type"]
    if kind == "boolean":
        if not isinstance(value, bool):
            raise fail(f"'{registration.analyzer_id}.{path}' must be true or false")
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (kind == "integer" and not isinstance(value, int)):
        raise fail(f"'{registration.analyzer_id}.{path}' must be a {'whole number' if kind == 'integer' else 'number'}")
    low, high = spec.get("min"), spec.get("max")
    if (low is not None and value < low) or (high is not None and value > high):
        raise fail(f"'{registration.analyzer_id}.{path}' must be between {low} and {high}, got {value}")


def _matches(pattern: str | None, value: str | None) -> bool:
    if pattern is None:
        return True
    return value is not None and fnmatch.fnmatchcase(value, pattern)


def _pattern_score(pattern: str | None) -> int:
    if pattern is None:
        return 0
    return 1 if any(char in pattern for char in "*?[") else 2


def _leaves(settings: dict[str, Any], prefix: str = ""):
    for key, value in settings.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            yield from _leaves(value, f"{path}.")
        else:
            yield path, value


def _get(params: dict[str, Any], dotted: str) -> Any:
    current: Any = params
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current
