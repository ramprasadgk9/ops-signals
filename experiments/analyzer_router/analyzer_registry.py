from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class AnalyzerCapability:
    analyzer: str
    display_name: str
    supported_profiles: list[str] = field(default_factory=list)
    eligibility_rules: dict[str, Any] = field(default_factory=dict)
    suitability_rules: dict[str, Any] = field(default_factory=dict)
    scoring_rules: dict[str, Any] = field(default_factory=dict)
    explanation_templates: dict[str, str] = field(default_factory=dict)


DEFAULT_REGISTRY_PATH = Path("experiments/analyzer_router/analyzer_registry.yaml")

DEFAULT_REGISTRY = {
    "analyzers": {
        "ruptures": {
            "display_name": "Ruptures",
            "supported_profiles": ["baseline_shift", "regime_change", "mixed", "trend"],
            "eligibility_rules": {"min_samples": 30, "requires_numeric": True},
            "suitability_rules": {
                "prefer_regular_sampling": True,
                "min_variance": 1e-9,
                "min_shift_index": 0.12,
                "bonus_shift_index": 0.22,
            },
            "explanation_templates": {
                "selected": "The series shows evidence of sustained baseline changes and enough samples for segment comparison.",
                "excluded": "The series lacks the minimum history or numeric stability needed for change-point detection.",
            },
        }
    }
}


class AnalyzerRegistry:
    def __init__(self, config_path: str | Path | None = None) -> None:
        self.config_path = Path(config_path) if config_path else None
        self.registry_version = "default"
        self._registry = self._load()

    def _load(self) -> dict[str, AnalyzerCapability]:
        raw: dict[str, Any] = {}
        source_path = self.config_path or DEFAULT_REGISTRY_PATH
        if source_path.exists():
            loaded = yaml.safe_load(source_path.read_text()) or {}
            self.registry_version = str(loaded.get("registry_version", source_path.stat().st_mtime_ns))
            raw.update(loaded.get("analyzers", loaded))
        else:
            self.registry_version = "default"
            raw.update(DEFAULT_REGISTRY.get("analyzers", {}))
        registry: dict[str, AnalyzerCapability] = {}
        for analyzer, data in raw.items():
            registry[analyzer] = AnalyzerCapability(
                analyzer=analyzer,
                display_name=data.get("display_name", analyzer.title()),
                supported_profiles=list(data.get("supported_profiles", [])),
                eligibility_rules=dict(data.get("eligibility_rules") or {}),
                suitability_rules=dict(data.get("suitability_rules") or {}),
                scoring_rules=dict(data.get("scoring_rules") or {}),
                explanation_templates=dict(data.get("explanation_templates") or {}),
            )
        return registry

    def analyzers(self) -> list[AnalyzerCapability]:
        return list(self._registry.values())

    def get(self, analyzer: str) -> AnalyzerCapability:
        return self._registry[analyzer]
