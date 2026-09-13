from __future__ import annotations

from pathlib import Path

import pytest

from experiments.analyzer_router import analyzer_registry as analyzer_registry_module
from experiments.analyzer_router.analyzer_registry import AnalyzerRegistry


def write_custom_registration(path: Path, filename: str, text: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / filename).write_text(text.strip(), encoding="utf-8")


@pytest.fixture(autouse=True)
def isolate_custom_registry_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test in this file gets its own empty custom registry directory by default, so tests
    never read or write the real repo's config/analyzer_registry.d/."""
    custom_dir = tmp_path / "analyzer_registry.d"
    monkeypatch.setattr(analyzer_registry_module, "DEFAULT_CUSTOM_REGISTRY_DIR", custom_dir)
    return custom_dir


def test_default_registry_still_includes_all_legacy_entries_unchanged() -> None:
    registry = AnalyzerRegistry()
    ids = {capability.analyzer for capability in registry.analyzers()}

    # These 11 come from the real experiments/analyzer_router/analyzer_registry.yaml - the merge
    # must never touch them when no custom registry directory is present.
    assert ids == {
        "ruptures",
        "stumpy",
        "prophet",
        "river",
        "kats",
        "darts",
        "alibi_detect",
        "trend_regression",
        "adtk",
        "pyod",
        "pyod_outlier",
    }
    ruptures = registry.get("ruptures")
    assert ruptures.display_name == "Ruptures"
    assert "baseline_shift" in ruptures.supported_profiles


def test_new_analyzer_with_router_block_becomes_visible(isolate_custom_registry_dir: Path) -> None:
    write_custom_registration(
        isolate_custom_registry_dir,
        "custom.yml",
        """
analyzers:
  my_forecast_model:
    display_name: My Forecast Model
    class_path: some.module.MyForecastAnalyzer
    router:
      supported_profiles: [forecast]
      eligibility_rules: {min_samples: 40}
      scoring_rules:
        base: 0.4
        rules:
          - {metric: seasonality_strength, gte: 0.5, add: 0.2}
      explanation_templates:
        selected: Custom forecast analyzer selected.
        excluded: Custom forecast analyzer excluded.
""",
    )

    registry = AnalyzerRegistry()

    ids = {capability.analyzer for capability in registry.analyzers()}
    assert "my_forecast_model" in ids
    capability = registry.get("my_forecast_model")
    assert capability.display_name == "My Forecast Model"
    assert capability.supported_profiles == ["forecast"]
    assert capability.eligibility_rules == {"min_samples": 40}
    assert capability.scoring_rules["base"] == 0.4
    assert "custom(my_forecast_model)" in registry.registry_version


def test_custom_analyzer_without_router_block_stays_invisible_to_the_router(isolate_custom_registry_dir: Path) -> None:
    write_custom_registration(
        isolate_custom_registry_dir,
        "custom.yml",
        """
analyzers:
  construction_only_analyzer:
    display_name: Construction Only
    class_path: some.module.SomeAnalyzer
""",
    )

    registry = AnalyzerRegistry()

    ids = {capability.analyzer for capability in registry.analyzers()}
    assert "construction_only_analyzer" not in ids


def test_custom_registration_never_overrides_an_existing_legacy_id(isolate_custom_registry_dir: Path) -> None:
    write_custom_registration(
        isolate_custom_registry_dir,
        "custom.yml",
        """
analyzers:
  ruptures:
    display_name: A Completely Different Ruptures
    class_path: some.module.ImpostorAnalyzer
    router:
      supported_profiles: [totally_different]
      scoring_rules:
        base: 0.99
        rules: []
""",
    )

    registry = AnalyzerRegistry()

    ruptures = registry.get("ruptures")
    assert ruptures.display_name == "Ruptures"
    assert "baseline_shift" in ruptures.supported_profiles
    assert "totally_different" not in ruptures.supported_profiles


def test_explicit_config_path_is_not_merged_with_the_custom_directory(
    tmp_path: Path, isolate_custom_registry_dir: Path
) -> None:
    write_custom_registration(
        isolate_custom_registry_dir,
        "custom.yml",
        """
analyzers:
  my_forecast_model:
    display_name: My Forecast Model
    class_path: some.module.MyForecastAnalyzer
    router:
      supported_profiles: [forecast]
      scoring_rules:
        base: 0.4
        rules: []
""",
    )
    explicit_registry_file = tmp_path / "explicit_registry.yaml"
    explicit_registry_file.write_text(
        """
registry_version: "test"
analyzers:
  only_analyzer:
    display_name: Only Analyzer
    supported_profiles: [trend]
""".strip(),
        encoding="utf-8",
    )

    registry = AnalyzerRegistry(config_path=explicit_registry_file)

    ids = {capability.analyzer for capability in registry.analyzers()}
    assert ids == {"only_analyzer"}
    assert "my_forecast_model" not in ids


def test_missing_custom_registry_directory_is_a_safe_no_op() -> None:
    registry = AnalyzerRegistry()
    assert registry.registry_version == "default" or "+custom" not in registry.registry_version
