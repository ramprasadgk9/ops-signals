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
# Where new analyzers register themselves (see intelligence/analyzer_registry.py) - merged in
# additively below, never overriding an id already present in the legacy file above. Existing
# routing behavior for every analyzer already in analyzer_registry.yaml is untouched by this;
# this only makes a *new* analyzer's own `router:` block visible to the real production router,
# which previously had no way to see anything registered outside this one file.
DEFAULT_CUSTOM_REGISTRY_DIR = Path("config/analyzer_registry.d")

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
    def __init__(self, config_path: str | Path | None = None, *, merge_custom: bool = True) -> None:
        self.config_path = Path(config_path) if config_path else None
        self.registry_version = "default"
        self._registry = self._load()
        if merge_custom and self.config_path is None:
            self._merge_custom_registrations()

    def _merge_custom_registrations(self) -> None:
        """Additively merges in analyzers registered via DEFAULT_CUSTOM_REGISTRY_DIR that declare
        a non-empty `router` block, so a newly added analyzer becomes visible to the real
        production router without needing a hand-added entry in the legacy
        analyzer_registry.yaml file. Only used for the default (no explicit config_path)
        instantiation - preview/test paths that pass an explicit path (e.g. admin_analyzers.py's
        test_route, or a tmp_path in tests) are unaffected, same as before this existed.

        Deliberately additive-only: an id already present in the legacy file is left exactly as
        that file defines it, never overridden here. This keeps every analyzer already in
        analyzer_registry.yaml routing exactly as it did before - this only ever *adds* ids that
        weren't there.
        """
        if not DEFAULT_CUSTOM_REGISTRY_DIR.exists():
            return
        from intelligence.analyzer_registry import load_registrations

        added: list[str] = []
        for registration in load_registrations(DEFAULT_CUSTOM_REGISTRY_DIR):
            if registration.analyzer_id in self._registry:
                continue
            if not registration.router.supported_profiles and not registration.router.scoring_rules:
                continue  # no router opt-in declared for this analyzer; stays construction-only
            self._registry[registration.analyzer_id] = AnalyzerCapability(
                analyzer=registration.analyzer_id,
                display_name=registration.display_name,
                supported_profiles=list(registration.router.supported_profiles),
                eligibility_rules=dict(registration.router.eligibility_rules),
                suitability_rules={},
                scoring_rules=dict(registration.router.scoring_rules),
                explanation_templates=dict(registration.router.explanation_templates),
            )
            added.append(registration.analyzer_id)
        if added:
            self.registry_version = f"{self.registry_version}+custom({','.join(sorted(added))})"

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
