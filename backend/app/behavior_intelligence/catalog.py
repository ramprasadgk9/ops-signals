from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import BehaviorDefinition

# Each shape a catalog signal can have: the condition that checks it and the analyzers that see it.
# Only shapes an input's own signals can show - an input with no signals makes the rule skip, so
# "did not change" can't be expressed (see config/behavior_patterns_catalog.yml).
SHAPES: dict[str, dict[str, Any]] = {
    "rising": {"fact": "change.upward", "analyzers": ["trend", "baseline_shift", "ruptures"]},
    "falling": {"fact": "change.downward", "analyzers": ["trend", "baseline_shift", "ruptures"]},
    "unusual": {"fact": "anomaly.present", "analyzers": ["anomaly_zscore", "pyod_outlier"]},
}
DEFAULT_CORRELATION = {"same_analysis_context": True, "max_time_gap": "30m", "minimum_overlap": "5m"}


class CatalogError(ValueError):
    pass


def _template_draft(entry: dict[str, Any]) -> dict[str, Any]:
    """The definition "Use this pattern" starts from: every signal must show its shape, together."""
    signals = entry["signals"]
    return {
        "id": entry["key"],
        "title": entry["name"],
        "description": entry["meaning"],
        "inputs": [
            {"alias": signal["alias"], "metric_name": signal["metric_hint"], "analyzers": SHAPES[signal["shape"]]["analyzers"]}
            for signal in signals
        ],
        "conditions": {
            "all": [
                {"fact": f"{signal['alias']}.{SHAPES[signal['shape']]['fact']}", "operator": "equals", "value": True}
                for signal in signals
            ],
            "any": [],
        },
        "correlation": dict(entry.get("correlation") or DEFAULT_CORRELATION),
        "output": {
            "category": entry.get("category", "behavior"),
            "severity": entry.get("severity", "medium"),
            "title": entry["name"],
            "summary": " ".join(str(entry["meaning"]).split()),
            "evidence": [f"{signal['alias']}.change.signed_change_percent" if signal["shape"] != "unusual" else f"{signal['alias']}.anomaly.count" for signal in signals],
        },
    }


def load_catalog(path: str | Path, definitions: list[BehaviorDefinition]) -> list[dict[str, Any]]:
    """The catalog's entries, rules first and in file order, each with what the page shows.

    A rule entry takes its name and meaning from the shipped definition and its proof from
    `scenarios`; a template carries its signals and a draft definition. Raises CatalogError for an
    entry the page could not show truthfully: an unknown rule, a template without signals, or a
    shape the engine can't check."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    by_id = {definition.id: definition for definition in definitions}
    entries: list[dict[str, Any]] = []
    for entry in raw.get("patterns", []) or []:
        if "rule" in entry:
            definition = by_id.get(entry["rule"])
            if definition is None:
                raise CatalogError(f"catalog names rule '{entry['rule']}', which no pack defines")
            scenarios = list(entry.get("scenarios") or [])
            entries.append({
                "key": definition.id,
                "rule": definition.id,
                "name": definition.title,
                "meaning": " ".join(definition.description.split()),
                "proof": "tested" if scenarios else "shipped",
                "scenarios": scenarios,
            })
            continue
        signals = entry.get("signals") or []
        if len(signals) < 2:
            raise CatalogError(f"template '{entry.get('key')}' needs at least two signals")
        for signal in signals:
            if signal.get("shape") not in SHAPES:
                raise CatalogError(f"template '{entry.get('key')}' signal '{signal.get('alias')}' has shape '{signal.get('shape')}', not one of {sorted(SHAPES)}")
        entries.append({
            "key": entry["key"],
            "rule": None,
            "name": entry["name"],
            "area": entry.get("area"),
            "meaning": " ".join(str(entry["meaning"]).split()),
            "why": " ".join(str(entry.get("why", "")).split()),
            "check_first": entry.get("check_first", ""),
            "proof": "common",
            "scenarios": [],
            "signals": [
                {
                    "alias": signal["alias"],
                    "label": signal["label"],
                    "shape": signal["shape"],
                    "metric_hint": signal["metric_hint"],
                    "keywords": list(signal.get("keywords") or []),
                    "analyzers": SHAPES[signal["shape"]]["analyzers"],
                }
                for signal in signals
            ],
            "draft": _template_draft(entry),
        })
    return entries
