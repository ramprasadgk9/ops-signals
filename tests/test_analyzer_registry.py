from __future__ import annotations

from pathlib import Path

import pytest

from intelligence.analyzer_registry import (
    AnalyzerRegistrationError,
    instantiate,
    load_registrations,
)


def write_registry(path: Path, filename: str, text: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / filename).write_text(text.strip(), encoding="utf-8")


def test_loads_a_single_valid_class_path_analyzer(tmp_path: Path) -> None:
    registry_dir = tmp_path / "analyzer_registry.d"
    write_registry(
        registry_dir,
        "custom.yml",
        """
analyzers:
  cpu_forecast:
    display_name: CPU Forecast
    enabled: true
    class_path: intelligence.analyzers.trend.TrendAnalyzer
    router:
      supported_profiles: [trend]
      eligibility_rules: {min_samples: 30}
      scoring_rules:
        base: 0.4
        rules:
          - {metric: trend_strength, gte: 0.2, add: 0.2}
      router_ids: [cpu_forecast_router]
    runtime_params:
      min_slope_percent: 12
""",
    )

    registrations = load_registrations(registry_dir)

    assert len(registrations) == 1
    reg = registrations[0]
    assert reg.analyzer_id == "cpu_forecast"
    assert reg.display_name == "CPU Forecast"
    assert reg.enabled is True
    assert reg.source_file == "custom.yml"
    assert reg.class_path == "intelligence.analyzers.trend.TrendAnalyzer"
    assert reg.http is None
    assert reg.router.supported_profiles == ["trend"]
    assert reg.router.eligibility_rules == {"min_samples": 30}
    assert reg.router.router_ids == ["cpu_forecast_router"]
    assert reg.runtime_params == {"min_slope_percent": 12}


def test_loads_every_yaml_file_in_a_directory(tmp_path: Path) -> None:
    registry_dir = tmp_path / "analyzer_registry.d"
    write_registry(
        registry_dir,
        "a.yml",
        """
analyzers:
  analyzer_a:
    display_name: A
    class_path: intelligence.analyzers.trend.TrendAnalyzer
""",
    )
    write_registry(
        registry_dir,
        "b.yaml",
        """
analyzers:
  analyzer_b:
    display_name: B
    class_path: intelligence.analyzers.trend.TrendAnalyzer
""",
    )

    registrations = load_registrations(registry_dir)

    assert {r.analyzer_id for r in registrations} == {"analyzer_a", "analyzer_b"}


def test_nonexistent_directory_returns_empty_list_without_crashing(tmp_path: Path) -> None:
    assert load_registrations(tmp_path / "does_not_exist") == []


def test_invalid_yaml_in_one_file_does_not_block_other_files(tmp_path: Path) -> None:
    registry_dir = tmp_path / "analyzer_registry.d"
    write_registry(registry_dir, "broken.yml", "analyzers:\n  - this is not valid: [yaml: :::")
    write_registry(
        registry_dir,
        "good.yml",
        """
analyzers:
  good_analyzer:
    display_name: Good
    class_path: intelligence.analyzers.trend.TrendAnalyzer
""",
    )

    registrations = load_registrations(registry_dir)

    assert [r.analyzer_id for r in registrations] == ["good_analyzer"]


def test_entry_missing_both_class_path_and_http_is_skipped(tmp_path: Path) -> None:
    registry_dir = tmp_path / "analyzer_registry.d"
    write_registry(
        registry_dir,
        "bad.yml",
        """
analyzers:
  incomplete:
    display_name: Incomplete
""",
    )

    assert load_registrations(registry_dir) == []


def test_entry_with_both_class_path_and_http_is_skipped(tmp_path: Path) -> None:
    registry_dir = tmp_path / "analyzer_registry.d"
    write_registry(
        registry_dir,
        "bad.yml",
        """
analyzers:
  ambiguous:
    display_name: Ambiguous
    class_path: intelligence.analyzers.trend.TrendAnalyzer
    http:
      analyze_url: https://example.com/analyze
""",
    )

    assert load_registrations(registry_dir) == []


def test_http_entry_without_analyze_url_is_skipped(tmp_path: Path) -> None:
    registry_dir = tmp_path / "analyzer_registry.d"
    write_registry(
        registry_dir,
        "bad.yml",
        """
analyzers:
  broken_http:
    display_name: Broken HTTP
    http:
      health_check_url: https://example.com/health
""",
    )

    assert load_registrations(registry_dir) == []


def test_valid_http_entry_parses_into_http_spec(tmp_path: Path) -> None:
    registry_dir = tmp_path / "analyzer_registry.d"
    write_registry(
        registry_dir,
        "http.yml",
        """
analyzers:
  remote_model:
    display_name: Remote Model
    http:
      analyze_url: https://example.com/analyze
      health_check_url: https://example.com/health
      timeout_seconds: 45
    router:
      supported_profiles: [forecast]
""",
    )

    registrations = load_registrations(registry_dir)

    assert len(registrations) == 1
    reg = registrations[0]
    assert reg.class_path is None
    assert reg.http is not None
    assert reg.http.analyze_url == "https://example.com/analyze"
    assert reg.http.health_check_url == "https://example.com/health"
    assert reg.http.timeout_seconds == 45


def test_duplicate_analyzer_id_across_files_keeps_the_first(tmp_path: Path) -> None:
    registry_dir = tmp_path / "analyzer_registry.d"
    write_registry(
        registry_dir,
        "a_first.yml",
        """
analyzers:
  dup:
    display_name: First
    class_path: intelligence.analyzers.trend.TrendAnalyzer
""",
    )
    write_registry(
        registry_dir,
        "b_second.yml",
        """
analyzers:
  dup:
    display_name: Second
    class_path: intelligence.analyzers.trend.TrendAnalyzer
""",
    )

    registrations = load_registrations(registry_dir)

    assert len(registrations) == 1
    assert registrations[0].display_name == "First"
    assert registrations[0].source_file == "a_first.yml"


def test_scoring_rule_with_unknown_metric_is_skipped(tmp_path: Path) -> None:
    registry_dir = tmp_path / "analyzer_registry.d"
    write_registry(
        registry_dir,
        "bad.yml",
        """
analyzers:
  bad_metric:
    display_name: Bad Metric
    class_path: intelligence.analyzers.trend.TrendAnalyzer
    router:
      scoring_rules:
        base: 0.3
        rules:
          - {metric: not_a_real_metric, gte: 0.2, add: 0.1}
""",
    )

    assert load_registrations(registry_dir) == []


def test_scoring_rule_with_zero_or_multiple_operators_is_skipped(tmp_path: Path) -> None:
    registry_dir = tmp_path / "analyzer_registry.d"
    write_registry(
        registry_dir,
        "bad.yml",
        """
analyzers:
  bad_operator:
    display_name: Bad Operator
    class_path: intelligence.analyzers.trend.TrendAnalyzer
    router:
      scoring_rules:
        base: 0.3
        rules:
          - {metric: trend_strength, add: 0.1}
""",
    )

    assert load_registrations(registry_dir) == []


def test_instantiate_constructs_a_real_analyzer_from_class_path() -> None:
    from intelligence.analyzer_registry import AnalyzerRegistration, RouterSpec

    registration = AnalyzerRegistration(
        analyzer_id="trend",
        display_name="Trend",
        enabled=True,
        source_file="test.yml",
        class_path="intelligence.analyzers.trend.TrendAnalyzer",
        http=None,
        router=RouterSpec(),
        runtime_params={"min_slope_percent": 15},
    )

    instance = instantiate(registration)

    assert instance.analyzer_id == "trend"
    assert instance.min_slope_percent == 15


def test_instantiate_applies_overrides_on_top_of_runtime_params() -> None:
    from intelligence.analyzer_registry import AnalyzerRegistration, RouterSpec

    registration = AnalyzerRegistration(
        analyzer_id="trend",
        display_name="Trend",
        enabled=True,
        source_file="test.yml",
        class_path="intelligence.analyzers.trend.TrendAnalyzer",
        http=None,
        router=RouterSpec(),
        runtime_params={"min_slope_percent": 15},
    )

    instance = instantiate(registration, overrides={"min_slope_percent": 40})

    assert instance.min_slope_percent == 40


def test_instantiate_raises_clear_error_for_missing_module() -> None:
    from intelligence.analyzer_registry import AnalyzerRegistration, RouterSpec

    registration = AnalyzerRegistration(
        analyzer_id="ghost",
        display_name="Ghost",
        enabled=True,
        source_file="test.yml",
        class_path="does.not.exist.GhostAnalyzer",
        http=None,
        router=RouterSpec(),
    )

    with pytest.raises(AnalyzerRegistrationError, match="could not import module"):
        instantiate(registration)


def test_instantiate_raises_clear_error_for_missing_class() -> None:
    from intelligence.analyzer_registry import AnalyzerRegistration, RouterSpec

    registration = AnalyzerRegistration(
        analyzer_id="ghost",
        display_name="Ghost",
        enabled=True,
        source_file="test.yml",
        class_path="intelligence.analyzers.trend.NotAClass",
        http=None,
        router=RouterSpec(),
    )

    with pytest.raises(AnalyzerRegistrationError, match="not found in module"):
        instantiate(registration)


def test_instantiate_raises_clear_error_when_class_is_not_an_analyzer_subclass() -> None:
    from intelligence.analyzer_registry import AnalyzerRegistration, RouterSpec

    registration = AnalyzerRegistration(
        analyzer_id="not_an_analyzer",
        display_name="Not An Analyzer",
        enabled=True,
        source_file="test.yml",
        class_path="pathlib.Path",
        http=None,
        router=RouterSpec(),
    )

    with pytest.raises(AnalyzerRegistrationError, match="is not an Analyzer subclass"):
        instantiate(registration)


def test_instantiate_raises_clear_error_for_bad_constructor_kwargs() -> None:
    from intelligence.analyzer_registry import AnalyzerRegistration, RouterSpec

    registration = AnalyzerRegistration(
        analyzer_id="trend",
        display_name="Trend",
        enabled=True,
        source_file="test.yml",
        class_path="intelligence.analyzers.trend.TrendAnalyzer",
        http=None,
        router=RouterSpec(),
        runtime_params={"not_a_real_param": 1},
    )

    with pytest.raises(AnalyzerRegistrationError, match="failed to construct"):
        instantiate(registration)


def test_instantiate_builds_an_http_analyzer_for_http_registrations() -> None:
    from intelligence.analyzer_registry import AnalyzerRegistration, HttpAnalyzerSpec, RouterSpec

    registration = AnalyzerRegistration(
        analyzer_id="remote_model",
        display_name="Remote Model",
        enabled=True,
        source_file="test.yml",
        class_path=None,
        http=HttpAnalyzerSpec(analyze_url="https://example.com/analyze"),
        router=RouterSpec(),
    )

    from intelligence.analyzers.http_analyzer import HttpAnalyzer

    assert isinstance(instantiate(registration), HttpAnalyzer)


def _pyod_registration():
    from intelligence.analyzer_registry import AnalyzerRegistration, RouterSpec

    return AnalyzerRegistration(
        analyzer_id="pyod_outlier",
        display_name="PyOD",
        enabled=True,
        source_file="test.yml",
        class_path="intelligence.analyzers.pyod_outlier.PyODOutlierAnalyzer",
        http=None,
        router=RouterSpec(),
        runtime_params={
            "implementation": {"library": "pyod", "detector_type": "knn", "contamination": 0.01, "grouping_gap": "15m", "min_samples": 75},
            # Not the analyzer's own defaults, so a lost key would show.
            "finding_rule": {"min_range_excess": 0.9, "min_sustained_points": 8, "window": "30m"},
        },
    )


def test_instantiate_merges_nested_overrides_key_by_key() -> None:
    registration = _pyod_registration()

    instance = instantiate(registration, overrides={"finding_rule": {"min_sustained_points": 12}, "implementation": {"contamination": 0.05}})

    # The keys the override sets change; the ones next to them keep their registered values.
    assert instance.config.finding_min_sustained_points == 12
    assert instance.config.finding_min_range_excess == 0.9
    assert str(instance.config.finding_window) == "0 days 00:30:00"
    assert instance.config.contamination == 0.05
    assert instance.config.min_samples == 75
    assert registration.runtime_params["finding_rule"]["min_sustained_points"] == 8


def test_instantiate_merges_http_analyzer_params_key_by_key() -> None:
    from intelligence.analyzer_registry import AnalyzerRegistration, HttpAnalyzerSpec, RouterSpec

    registration = AnalyzerRegistration(
        analyzer_id="remote_model",
        display_name="Remote Model",
        enabled=True,
        source_file="test.yml",
        class_path=None,
        http=HttpAnalyzerSpec(analyze_url="https://example.com/analyze"),
        router=RouterSpec(),
        runtime_params={"finding_rules": {"min_score": 0.8, "min_points": 10}},
    )

    instance = instantiate(registration, overrides={"finding_rules": {"min_score": 0.6}})

    assert instance.params["finding_rules"] == {"min_score": 0.6, "min_points": 10}
