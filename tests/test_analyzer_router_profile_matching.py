from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from experiments.analyzer_router.models import SeriesProfile
from experiments.analyzer_router.router import UniversalTimeSeriesRouter


def _extract_profile(values: list[float] | pd.Series) -> SeriesProfile:
    timestamps = pd.date_range("2026-01-01", periods=len(values), freq="5min", tz="UTC")
    dataframe = pd.DataFrame({"timestamp": timestamps, "value": values})
    router = UniversalTimeSeriesRouter()
    validation, profile, _ = router.profile_dataframe(dataframe, "timestamp", "value")
    assert validation.valid is True
    return profile


def _profile(**overrides) -> SeriesProfile:
    values = {
        "original_sample_count": 120,
        "valid_sample_count": 120,
        "invalid_timestamp_count": 0,
        "invalid_value_count": 0,
        "missing_percentage": 0.0,
        "duplicate_timestamp_count": 0,
        "sampling_interval_seconds": 300,
        "duration_seconds": 35700,
        "irregular_sampling_percentage": 0.0,
        "interpolated_sample_count": 0,
        "interpolated_percentage": 0.0,
        "constant_value_percentage": 0.0,
        "sample_count": 120,
        "regular_sampling": True,
        "mean": 42.0,
        "stddev": 5.0,
        "minimum": 30.0,
        "maximum": 60.0,
        "variance": 25.0,
        "trend_slope": 0.0,
        "trend_strength": 0.0,
        "seasonality_strength": 0.0,
        "spikiness": 0.0,
        "shift_index": 0.0,
        "autocorrelation": None,
        "trend_fit_r2": 0.0,
        "trend_abruptness_ratio": 0.0,
        "seasonality_dominant_lag": None,
        "seasonality_peak_strength": 0.0,
        "transient_spike_count": 0,
        "persistent_jump_count": 0,
        "detected_profiles": [],
        "notes": [],
    }
    values.update(overrides)
    return SeriesProfile(**values)


def test_feature_extractor_detects_pure_baseline_step_without_false_profiles() -> None:
    profile = _extract_profile([30.0] * 1008 + [60.0] * 1008)

    assert profile.shift_index >= 0.22
    assert profile.trend_strength < 0.18
    assert profile.seasonality_strength < 0.42
    assert profile.spikiness < 0.22
    assert profile.persistent_jump_count == 1
    assert profile.detected_profiles == ["baseline_shift", "regime_change"]


def test_feature_extractor_detects_negative_baseline_step_without_spike_profile() -> None:
    profile = _extract_profile([60.0] * 1008 + [30.0] * 1008)

    assert profile.shift_index >= 0.22
    assert profile.spikiness < 0.22
    assert profile.persistent_jump_count == 1
    assert profile.detected_profiles == ["baseline_shift", "regime_change"]


def test_feature_extractor_treats_linear_ramp_as_trend_not_baseline_shift() -> None:
    values = pd.Series([30.0 + (30.0 * index / 239.0) for index in range(240)])
    profile = _extract_profile(values)

    assert profile.trend_strength >= 0.18
    assert profile.persistent_jump_count == 0
    assert "trend" in profile.detected_profiles
    assert "baseline_shift" not in profile.detected_profiles
    assert "regime_change" not in profile.detected_profiles


def test_feature_extractor_detects_trend_and_baseline_shift_when_both_exist() -> None:
    values = [30.0 + (12.0 * index / 239.0) + (20.0 if index >= 120 else 0.0) for index in range(240)]
    profile = _extract_profile(values)

    assert "baseline_shift" in profile.detected_profiles
    assert "regime_change" in profile.detected_profiles
    assert "trend" in profile.detected_profiles
    assert "mixed" in profile.detected_profiles


def test_feature_extractor_detects_repeating_seasonal_series() -> None:
    values = pd.Series([50.0 + 10.0 * math.sin(index * 2.0 * math.pi / 24.0) for index in range(240)])
    profile = _extract_profile(values)

    assert profile.seasonality_strength >= 0.42
    assert profile.seasonality_dominant_lag == 24
    assert "seasonal" in profile.detected_profiles
    assert "repeating_pattern" in profile.detected_profiles
    assert "trend" not in profile.detected_profiles


def test_feature_extractor_distinguishes_transient_spikes_from_permanent_jumps() -> None:
    values = [50.0] * 240
    values[80] = 85.0
    values[150] = 15.0
    profile = _extract_profile(values)

    assert profile.spikiness >= 0.22
    assert profile.transient_spike_count >= 2
    assert "spike" in profile.detected_profiles

    step_profile = _extract_profile([50.0] * 120 + [80.0] * 120)
    assert step_profile.spikiness < 0.22
    assert step_profile.persistent_jump_count == 1
    assert "spike" not in step_profile.detected_profiles


def test_supported_profile_mismatch_caps_suitability(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text(
        """
registry_version: test
analyzers:
  seasonal_tool:
    display_name: Seasonal Tool
    supported_profiles:
      - seasonal
    eligibility_rules:
      min_samples: 30
      requires_numeric: true
    scoring_rules:
      base: 0.95
""".strip(),
        encoding="utf-8",
    )
    router = UniversalTimeSeriesRouter(registry_path=registry_path)

    decision = router.recommend_analyzers_for_profile(
        _profile(detected_profiles=["baseline_shift"], shift_index=0.3)
    )[0]

    assert decision.eligible is True
    assert decision.final_score == 0.54
    assert decision.recommendation == "NOT_RECOMMENDED"
    assert decision.parameters_tested["profile_match"] is False
    assert decision.parameters_tested["behavioral_supported_profiles"] == ["seasonal"]
    assert "No supported behavioral profile matched" in decision.reasons[1]


def test_supported_profile_match_adds_metadata_and_bonus(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text(
        """
registry_version: test
analyzers:
  change_tool:
    display_name: Change Tool
    supported_profiles:
      - baseline_shift
      - forecast
    eligibility_rules:
      min_samples: 30
      requires_numeric: true
    scoring_rules:
      base: 0.70
""".strip(),
        encoding="utf-8",
    )
    router = UniversalTimeSeriesRouter(registry_path=registry_path)

    decision = router.recommend_analyzers_for_profile(
        _profile(detected_profiles=["baseline_shift", "trend"], shift_index=0.3)
    )[0]

    assert decision.final_score == 0.8
    assert decision.recommendation == "RECOMMENDED"
    assert decision.parameters_tested["detected_profiles"] == ["baseline_shift", "trend"]
    assert decision.parameters_tested["matched_profiles"] == ["baseline_shift"]
    assert decision.parameters_tested["profile_match"] is True
    assert decision.parameters_tested["behavioral_supported_profiles"] == ["baseline_shift"]
    assert "Matched detected profiles: baseline_shift." in decision.reasons[1]


def test_non_behavior_supported_profiles_are_unrestricted_without_bonus(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text(
        """
registry_version: test
analyzers:
  streaming_tool:
    display_name: Streaming Tool
    supported_profiles:
      - streaming
      - forecast
    eligibility_rules:
      min_samples: 30
      requires_numeric: true
    scoring_rules:
      base: 0.50
""".strip(),
        encoding="utf-8",
    )
    router = UniversalTimeSeriesRouter(registry_path=registry_path)

    decision = router.recommend_analyzers_for_profile(
        _profile(detected_profiles=["baseline_shift"], shift_index=0.3)
    )[0]

    assert decision.final_score == 0.5
    assert decision.recommendation == "NOT_RECOMMENDED"
    assert decision.parameters_tested["profile_match"] is True
    assert decision.parameters_tested["behavioral_supported_profiles"] == []
    assert "No behavioral profile restriction is configured" in decision.reasons[1]


def test_pyod_outlier_is_recommended_for_spiky_profile() -> None:
    router = UniversalTimeSeriesRouter()
    decisions = {
        decision.analyzer: decision
        for decision in router.recommend_analyzers_for_profile(
            _profile(detected_profiles=["spike", "anomaly", "outlier"], spikiness=0.4)
        )
    }

    decision = decisions["pyod_outlier"]
    assert decision.eligible is True
    assert decision.recommendation == "RECOMMENDED"
    assert decision.parameters_tested["matched_profiles"] == ["anomaly", "outlier", "spike"]


def test_pyod_outlier_is_not_recommended_for_baseline_shift_profile() -> None:
    router = UniversalTimeSeriesRouter()
    decisions = {
        decision.analyzer: decision
        for decision in router.recommend_analyzers_for_profile(
            _profile(detected_profiles=["baseline_shift", "regime_change"], shift_index=0.3, spikiness=0.0)
        )
    }

    decision = decisions["pyod_outlier"]
    assert decision.eligible is True
    assert decision.recommendation == "NOT_RECOMMENDED"
    assert decision.parameters_tested["profile_match"] is False
