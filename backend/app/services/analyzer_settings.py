"""The analyzer settings analysis runs use, and which file each value comes from.

A setting can be set in four places, each overriding the one before it, key by key:

1. the built-in defaults, `runtime_params` in config/analyzer_registry.d/*.yml;
2. the site, `analysis.analyzers` in config/analyzers.yaml;
3. the data source, `analysis.analyzers` in config/providers/<provider>.yaml (Prometheus runs use
   prometheus.yaml, OTLP runs otel.yaml);
4. a team's services, config/analyzer_overrides.d/*.yml, for the services and metrics they scope.

Analyzer Labs are a sandbox: their values only reach the one lab run. This module reads the same
files and helpers the pipeline does (load_registrations, load_overrides, deep_merge) so the Settings
in use page can't disagree with what a run does. Settings are named by their path in
config/analyzers.yaml, the shape people write, not the shape the constructors take.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from intelligence.analyzer_overrides import AnalyzerOverride, _leaves, load_overrides
from intelligence.analyzer_registry import AnalyzerRegistration, library_installed, load_registrations

_REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = _REPO_ROOT / "config"

# Data sources whose scheduled runs read a provider file, and that file.
PROVIDERS = {"prometheus": "Prometheus", "otel": "OTLP"}

# baseline_shift and ruptures take flat constructor arguments; config/analyzers.yaml writes them in
# blocks (intelligence/analyzer_selection.py, _baseline_shift_params). Flat name -> the path people
# write. The older statistical_gate / operational_significance blocks mean the same settings.
_BASELINE_PATHS = {
    "threshold_percent": "finding_rules.min_change_percent",
    "change_threshold": "finding_rules.min_effect_size",
    "min_segment_size": "ruptures.min_size",
    "ruptures_algorithm": "ruptures.algorithm",
    "ruptures_model": "ruptures.model",
    "ruptures_jump": "ruptures.jump",
    "ruptures_n_bkps": "ruptures.n_bkps",
    "operational_significance.min_change_percent": "finding_rules.min_change_percent",
    "statistical_gate.min_effect_size": "finding_rules.min_effect_size",
}
LEGACY_PATHS = {
    "baseline_shift": _BASELINE_PATHS,
    "ruptures": {
        "min_segment_size": "ruptures.min_size",
        "change_threshold": "finding_rules.min_effect_size",
        "statistical_gate.min_effect_size": "finding_rules.min_effect_size",
    },
}

# How a run uses each analyzer, as `run.status`.
EVERY_METRIC = "every_metric"
ROUTER = "router"
ONLY_IF_CHOSEN = "only_if_chosen"
TURNED_OFF = "turned_off"
CANT_RUN = "cant_run"

# Why an analyzer the router never picks still has a use, in the docs' words
# (docs/analyzers-explained.md, "Overlapping analyzers: what runs by default").
ONLY_IF_CHOSEN_NOTES = {
    "anomaly_zscore": "PyOD Outlier covers spikes by default. Z-Score also runs on a spiky metric with too few points for PyOD (under 50).",
    "baseline_shift": "Ruptures covers level changes by default.",
}


# Whether the analyzer reads a setting, as `use` on each setting:
USED = "used"  # it changes what the analyzer does
LABEL = "label"  # only written into a finding's details; the analyzer always does the same thing
UNUSED = "unused"  # read in another mode only (see _mode_use)
UNKNOWN = "unknown"  # not a setting of this analyzer: probably a typo

# What each setting of the shipped analyzers does, checked against their code, and whether it's
# read. A `tunable` label in the registration wins over the meaning here.
SETTING_HELP: dict[str, dict[str, tuple[str, str]]] = {
    "baseline_shift": {
        "finding_rules.min_change_percent": (USED, "Smallest lasting change in level that counts, in %"),
        "finding_rules.min_effect_size": (USED, "How clearly the new level must stand apart from the old, in standard deviations"),
        "ruptures.min_size": (USED, "Fewest readings on each side of a change"),
        "ruptures.algorithm": (USED, "How the change is searched for. Only binseg is supported"),
        "ruptures.model": (USED, "How the difference between two stretches is measured (l2: by their averages)"),
        "ruptures.jump": (USED, "Only every Nth reading is tried as the change point; higher is faster but rougher"),
        "ruptures.n_bkps": (USED, "How many change points are looked for; the strongest one is reported"),
    },
    "ruptures": {
        "finding_rules.min_effect_size": (USED, "How clearly the new level must stand apart from the old, in standard deviations"),
        "ruptures.min_size": (USED, "Fewest readings on each side of a change"),
    },
    "anomaly_zscore": {
        "implementation.zscore_threshold": (USED, "Step 1: how far from the average, in standard deviations, a reading must be to count as unusual"),
        "finding_rules.min_abs_zscore": (USED, "Step 2: how far the most unusual reading of a group must be for the group to become a finding"),
        "finding_rules.min_points": (USED, "Fewest unusual readings a group needs to become a finding"),
        "implementation.grouping_gap": (USED, "Unusual readings closer together than this form one group"),
        "implementation.library": (LABEL, "Shown in the finding's details only"),
        "implementation.method": (LABEL, "Shown in the finding's details only; the method is always zscore"),
        "rebaseline.enabled": (USED, "When the metric's level changed partway, judge readings against the latest level only"),
        "rebaseline.min_segment_size": (USED, "Fewest readings on each side of such a level change"),
        "rebaseline.change_threshold": (USED, "How clear a level change must be to start from the new level"),
        "rebaseline.max_iterations": (USED, "Most level changes stepped over in one series"),
    },
    "pyod_outlier": {
        "implementation.detector_type": (USED, "The outlier detector. Only knn is supported"),
        "implementation.detector": (LABEL, "Shown in the finding's details only; detector_type picks the detector"),
        "implementation.library": (LABEL, "Shown in the finding's details only"),
        "implementation.contamination": (USED, "Share of readings the detector expects to be outliers"),
        "implementation.min_samples": (USED, "Fewest readings a series needs before PyOD looks at it"),
        "implementation.grouping_gap": (USED, "Outliers closer together than this form one group"),
        "finding_rule.window": (USED, "How close together outliers must be to count as one unusual stretch"),
        "finding_rule.compare_daily_peaks": (USED, "Quiet mode: a spike must also stand out from the metric's usual daily peaks"),
    },
    "trend": {
        "implementation.library": (LABEL, "Shown in the finding's details only"),
        "implementation.model": (LABEL, "Shown in the finding's details only; the trend is always a straight-line (OLS) fit"),
    },
    "stumpy": {
        "implementation.mode": (USED, "discord finds the series' most unusual stretches; motif finds its most repeated one"),
        "implementation.window_size": (USED, "Length of the stretches compared, in readings"),
        "implementation.max_discords": (USED, "Most unusual stretches reported per series"),
        "finding_rules.min_surprise": (USED, "How unlike the rest of the series a stretch must be to become a finding"),
        "implementation.motif_count": (USED, "Repeated stretches looked for"),
        "implementation.profile_threshold": (USED, "Distance at which a repeated stretch no longer counts as a match; sets the confidence"),
        "finding_rules.max_motif_distance": (USED, "Largest distance between two stretches that still counts as a repeat"),
        "finding_rules.min_confidence": (USED, "Lowest confidence a repeated stretch needs to become a finding"),
        "implementation.algorithm": (LABEL, "Shown in the finding's details only; stumpy's stump is always used"),
        "implementation.library": (LABEL, "Shown in the finding's details only"),
    },
    "prophet": {
        "implementation.horizon_points": (USED, "How many readings ahead the forecast reaches"),
        "implementation.changepoint_prior_scale": (USED, "How readily the forecast follows changes in the trend; higher bends more"),
        "implementation.uncertainty_threshold": (USED, "A miss twice this size, as a share of the forecast, makes the finding high severity"),
        "finding_rules.min_relative_error": (USED, "Smallest miss, as a share of the forecast, that becomes a finding"),
        "implementation.library": (LABEL, "Shown in the finding's details only"),
    },
    "data_health": {
        "gap_multiple": (USED, "A pause this many times the usual reporting interval counts as a gap"),
        "max_normal_missing_ratio": (USED, "A metric already missing more than this share of readings isn't reported for gaps"),
        "min_flatline_minutes": (USED, "Shortest time stuck at one value that counts"),
        "min_flatline_points": (USED, "Fewest readings stuck at one value that count"),
        "min_normal_change_ratio": (USED, "Only a metric that usually changes this often is reported when it gets stuck"),
    },
    "seasonal_anomaly": {
        "zscore_threshold": (USED, "How unusual a reading must be for that time of day or week"),
        "min_calendar_strength": (USED, "How clear the daily or weekly cycle must be before readings are judged against it"),
        "min_deviation_ratio": (USED, "Smallest miss that counts, as a share of the cycle's normal swing"),
        "min_relative_deviation": (USED, "Smallest miss that counts, as a share of the expected value"),
        "grouping_gap": (USED, "Unusual readings closer together than this form one finding"),
    },
}

# Settings an analyzer reads in one mode only: analyzer -> mode path -> mode -> paths read only then.
MODE_ONLY: dict[str, tuple[str, dict[str, set[str]]]] = {
    "stumpy": (
        "implementation.mode",
        {
            "discord": {"implementation.max_discords", "finding_rules.min_surprise"},
            "motif": {"implementation.motif_count", "implementation.profile_threshold", "finding_rules.max_motif_distance", "finding_rules.min_confidence"},
        },
    ),
}

# Analyzers whose settings look shared with another's but aren't.
SETTINGS_NOTES = {
    "ruptures": "Ruptures and Baseline Shift have separate settings: changing ruptures.min_size or finding_rules.min_effect_size here doesn't change Baseline Shift's. Ruptures always searches with binseg and the l2 model.",
    "baseline_shift": "Baseline Shift and Ruptures have separate settings: changing Baseline Shift's ruptures.* or finding_rules.* doesn't change the Ruptures analyzer.",
}


@dataclass(slots=True)
class _Layer:
    key: str
    file: str
    exists: bool
    params: dict[str, dict[str, Any]]
    enabled: dict[str, bool]


def settings_in_use(
    provider: str = "prometheus",
    service: str | None = None,
    metric: str | None = None,
    *,
    config_dir: Path = CONFIG_DIR,
    router_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Every analyzer with its run status and each setting's value, source and default.

    With a service and/or metric, a team's overrides that match them are applied too, exactly as
    a run of that series would (OverrideSet.resolve); without, the values are site-wide."""
    if provider not in PROVIDERS:
        raise ValueError(f"provider must be one of {sorted(PROVIDERS)}")
    service = (service or "").strip() or None
    metric = (metric or "").strip() or None
    registrations = load_registrations(config_dir / "analyzer_registry.d")
    site_raw = _read_yaml(config_dir / "analyzers.yaml")
    provider_raw = _read_yaml(config_dir / "providers" / f"{provider}.yaml")
    layers = [
        _layer("site", "config/analyzers.yaml", site_raw, (config_dir / "analyzers.yaml").exists()),
        _layer("provider", f"config/providers/{provider}.yaml", provider_raw, (config_dir / "providers" / f"{provider}.yaml").exists()),
    ]
    analysis = {**(site_raw.get("analysis") or {}), **(provider_raw.get("analysis") or {})}
    execution = {**((site_raw.get("analysis") or {}).get("recommendation_execution") or {}), **((provider_raw.get("analysis") or {}).get("recommendation_execution") or {})}
    selection = {
        "mode": str(analysis.get("selection_mode") or "all"),
        "min_score": float(execution.get("min_score", 0.8)),
        "max_analyzers": int(execution.get("max_analyzers", 3)),
        "include_optional": bool(execution.get("include_optional", False)),
        "selected_analyzers": [str(item) for item in analysis.get("selected_analyzers") or []],
        "max_analyzers_source": None,
    }

    override_set = load_overrides(config_dir / "analyzer_overrides.d", registrations)
    scoped = service is not None or metric is not None
    matching = _matching_overrides(override_set.overrides, service, metric) if scoped else []
    disabled_by: dict[str, AnalyzerOverride] = {}
    for override in matching:
        if override.max_analyzers is not None:
            selection["max_analyzers"] = override.max_analyzers
            selection["max_analyzers_source"] = _override_source(override)
        for analyzer_id in override.disabled:
            disabled_by.setdefault(analyzer_id, override)

    pickable = _router_pickable() if router_ids is None else router_ids
    analyzers = []
    for registration in registrations:
        analyzer_id = registration.analyzer_id
        settings = _resolve_settings(registration, layers, matching)
        enabled = registration.enabled
        enabled_source = "default"
        for layer in layers:
            if analyzer_id in layer.enabled:
                enabled, enabled_source = layer.enabled[analyzer_id], layer.key
        run = _run_status(registration, enabled, enabled_source, selection, pickable, disabled_by.get(analyzer_id))
        analyzers.append(
            {
                "analyzer_id": analyzer_id,
                "display_name": registration.display_name,
                "description": registration.description,
                "enabled": enabled,
                "run": run,
                "settings": settings,
                "settings_note": SETTINGS_NOTES.get(analyzer_id),
                "changed_count": sum(1 for setting in settings if setting["changed"]),
            }
        )

    files = sorted({override.source_file for override in override_set.overrides})
    return {
        "provider": provider,
        "provider_label": PROVIDERS[provider],
        "service": service,
        "metric": metric,
        "selection": selection,
        "layers": [
            {"key": "default", "title": "Built-in defaults", "file": "config/analyzer_registry.d/", "changed": None, "analyzers": len(registrations)},
            *(
                {"key": layer.key, "title": "Your site" if layer.key == "site" else "Data source", "file": layer.file, "exists": layer.exists, "changed": _count_changes(layer, registrations)}
                for layer in layers
            ),
            {
                "key": "override",
                "title": "A team's services",
                "file": "config/analyzer_overrides.d/",
                "files": len(files),
                "overrides": len(override_set.overrides),
                "applied": [override.override_id for override in matching],
                "errors": [{"file": error.source_file, "message": error.message} for error in override_set.errors],
            },
        ],
        "scopes": [
            {"override_id": override.override_id, "service": override.service, "metric": override.metric, "file": override.source_file, "reason": override.reason}
            for override in override_set.overrides
        ],
        "analyzers": analyzers,
    }


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _layer(key: str, file: str, raw: dict[str, Any], exists: bool) -> _Layer:
    params: dict[str, dict[str, Any]] = {}
    enabled: dict[str, bool] = {}
    for analyzer_id, details in ((raw.get("analysis") or {}).get("analyzers") or {}).items():
        if not isinstance(details, dict):
            continue
        if "enabled" in details:
            enabled[str(analyzer_id)] = bool(details["enabled"])
        params[str(analyzer_id)] = {name: value for name, value in details.items() if name != "enabled"}
    return _Layer(key=key, file=file, exists=exists, params=params, enabled=enabled)


def _count_changes(layer: _Layer, registrations: list[AnalyzerRegistration]) -> int:
    """Values this file sets differently from the built-in default. analyzers.yaml repeats many
    defaults word for word; those change nothing, so they aren't counted."""
    by_id = {registration.analyzer_id: registration for registration in registrations}
    changed = 0
    for analyzer_id, params in layer.params.items():
        registration = by_id.get(analyzer_id)
        defaults = _defaults(registration) if registration else {}
        changed += sum(1 for path, value in dict(_paths(analyzer_id, params)).items() if value != defaults.get(path))
    for analyzer_id, enabled in layer.enabled.items():
        registration = by_id.get(analyzer_id)
        changed += int(registration is None or enabled != registration.enabled)
    return changed


def _matching_overrides(overrides: list[AnalyzerOverride], service: str | None, metric: str | None) -> list[AnalyzerOverride]:
    """The overrides a run of this series applies, least specific first: the order and the match
    rule of OverrideSet.resolve, so a later one wins on a setting both change."""
    return sorted(
        (override for override in overrides if override.matches(service, metric)),
        key=lambda override: (override.specificity, override.source_file, override.override_id),
    )


def _override_source(override: AnalyzerOverride) -> dict[str, Any]:
    return {
        "layer": "override",
        "file": f"config/analyzer_overrides.d/{override.source_file}",
        "override_id": override.override_id,
        "reason": override.reason,
    }


def _paths(analyzer_id: str, params: dict[str, Any]) -> list[tuple[str, Any]]:
    """Leaves of one analyzer's settings, by their config/analyzers.yaml path. For the two legacy
    analyzers flat names become their block paths, and a block path wins over a flat name or an
    older block for the same setting, as in _baseline_shift_params."""
    aliases = LEGACY_PATHS.get(analyzer_id, {})
    leaves = [(aliases.get(path, path), path in aliases, value) for path, value in _leaves(params)]
    # Aliased (flat or older-block) leaves first, so a leaf written in the current shape wins.
    leaves.sort(key=lambda leaf: not leaf[1])
    return [(path, value) for path, _, value in leaves]


def _defaults(registration: AnalyzerRegistration) -> dict[str, Any]:
    """The registration's runtime_params by path. A top-level key repeated inside `implementation`
    is left out: the constructors read the `implementation` copy (e.g. ZScoreAnomalyAnalyzer)."""
    params = registration.runtime_params
    implementation = params.get("implementation") if isinstance(params.get("implementation"), dict) else {}
    defaults: dict[str, Any] = {}
    for path, value in _paths(registration.analyzer_id, params):
        if "." not in path and path in implementation:
            continue
        defaults[path] = value
    return defaults


def _resolve_settings(registration: AnalyzerRegistration, layers: list[_Layer], overrides: list[AnalyzerOverride]) -> list[dict[str, Any]]:
    analyzer_id = registration.analyzer_id
    defaults = _defaults(registration)
    values: dict[str, Any] = dict(defaults)
    sources: dict[str, dict[str, Any]] = {path: {"layer": "default", "file": f"config/analyzer_registry.d/{registration.source_file}"} for path in defaults}
    for layer in layers:
        for path, value in _paths(analyzer_id, layer.params.get(analyzer_id, {})):
            values[path] = value
            sources[path] = {"layer": layer.key, "file": layer.file}
    for override in overrides:
        for path, value in _paths(analyzer_id, override.analyzers.get(analyzer_id, {})):
            values[path] = value
            sources[path] = _override_source(override)
    help_for = SETTING_HELP.get(analyzer_id, {})
    settings = []
    for path in sorted(values, key=lambda item: (item.count("."), item)):
        tunable = registration.tunable.get(path)
        use, meaning = help_for.get(path, (USED, None))
        use_note = None
        if analyzer_id in SETTING_HELP and path not in help_for and path not in defaults and tunable is None:
            use, use_note = UNKNOWN, f"{registration.display_name} doesn't read this key. Check its spelling and where it sits."
        mode_note = _mode_use(analyzer_id, path, values)
        if mode_note:
            use, use_note = UNUSED, mode_note
        settings.append(
            {
                "path": path,
                "value": values[path],
                "default": defaults.get(path),
                "changed": values[path] != defaults.get(path),
                "source": sources[path],
                "use": use,
                "use_note": use_note,
                "meaning": (tunable or {}).get("label") or meaning,
                "label": (tunable or {}).get("label"),
                "per_service": tunable is not None,
                "min": (tunable or {}).get("min"),
                "max": (tunable or {}).get("max"),
            }
        )
    return settings


def _mode_use(analyzer_id: str, path: str, values: dict[str, Any]) -> str | None:
    """Why a setting isn't read in the mode the analyzer runs in, or None when it is."""
    if analyzer_id not in MODE_ONLY:
        return None
    mode_path, by_mode = MODE_ONLY[analyzer_id]
    mode = str(values.get(mode_path, "")).lower().strip()
    for other, paths in by_mode.items():
        if other != mode and path in paths:
            return f"Not used: read only when {mode_path.split('.')[-1]} is {other}, and it's {mode or 'not set'}."
    return None


def _router_pickable() -> set[str]:
    """Analyzer ids the router can choose on its own: its catalog (with the analyzers merged from
    config/analyzer_registry.d that declare a router block), mapped to pipeline ids."""
    from experiments.analyzer_router.analyzer_registry import AnalyzerRegistry
    from intelligence.analyzer_selection import RegistryAnalyzerSelection

    mapping = RegistryAnalyzerSelection._router_to_pipeline_analyzers()
    pickable: set[str] = set()
    for capability in AnalyzerRegistry().analyzers():
        pickable.update(mapping.get(capability.analyzer, {capability.analyzer}))
    return pickable


def _run_status(
    registration: AnalyzerRegistration,
    enabled: bool,
    enabled_source: str,
    selection: dict[str, Any],
    pickable: set[str],
    disabled_by: AnalyzerOverride | None,
) -> dict[str, Any]:
    """Whether a run uses the analyzer, with the reason in words: the order of checks follows
    RegistryAnalyzerSelection (turned off, then always_run, the selection mode, the router)."""
    analyzer_id = registration.analyzer_id
    mode = selection["mode"].lower().strip()
    missing_library = registration.requires_library if registration.requires_library and not library_installed(registration.requires_library) else None
    if not enabled:
        where = {"site": "config/analyzers.yaml", "provider": "the data source's file"}.get(enabled_source, "its registration")
        return {"status": TURNED_OFF, "text": f"Turned off (enabled: false in {where})."}
    if disabled_by is not None:
        return {"status": TURNED_OFF, "text": f"Turned off for these metrics by {disabled_by.override_id} in {disabled_by.source_file}.", "source": _override_source(disabled_by)}
    if registration.always_run:
        return {"status": EVERY_METRIC, "text": "Runs on every metric."}
    if mode == "all":
        text = "Runs on every metric: selection_mode is all."
        if missing_library:
            text += f" The {missing_library} library isn't installed, so it runs a simpler fallback."
        return {"status": EVERY_METRIC, "text": text}
    if missing_library:
        return {"status": CANT_RUN, "text": f"Turned on, but the {missing_library} library isn't installed, so the router never picks it."}
    if mode == "manual_override" and analyzer_id in selection["selected_analyzers"]:
        return {"status": EVERY_METRIC, "text": "Chosen in selected_analyzers, so it runs on every metric."}
    if analyzer_id in pickable:
        return {"status": ROUTER, "text": "The router picks it for a metric it suits."}
    text = "The router doesn't pick it on its own. It runs with selection_mode all, or listed in selected_analyzers with manual_override."
    note = ONLY_IF_CHOSEN_NOTES.get(analyzer_id)
    return {"status": ONLY_IF_CHOSEN, "text": text, **({"note": note} if note else {})}
