from __future__ import annotations

import math
from pathlib import Path

import numpy as np
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
    assert profile.seasonality_dominant_lag in (24, 48)
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


def test_seasonal_residual_returns_none_when_series_shorter_than_one_cycle() -> None:
    from experiments.analyzer_router.feature_extractor import _seasonal_residual

    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert _seasonal_residual(values, lag=10) is None
    assert _seasonal_residual(values, lag=0) is None
    assert _seasonal_residual(values, lag=-1) is None


def test_seasonal_residual_compares_each_point_to_one_cycle_back() -> None:
    from experiments.analyzer_router.feature_extractor import _seasonal_residual

    values = np.array([10.0, 20.0, 30.0, 11.0, 19.0, 33.0])
    residual = _seasonal_residual(values, lag=3)
    assert residual is not None
    np.testing.assert_allclose(residual, [1.0, -1.0, 3.0])


def test_spikiness_uses_seasonal_residual_to_catch_anomaly_hidden_by_daily_swing() -> None:
    # Taxi-shaped series: a strong daily rhythm (period 24, amplitude +-40) across 10 days, with a
    # brief real anomaly (5 points) pushed 30 lower than normal on one day. A raw point-to-point
    # jump check misses this entirely (spikiness stays 0.0) because the everyday rush-hour swing
    # (+-40 per half-day) is bigger than the anomaly's own jump against its immediate neighbour.
    # Values confirmed against the real nab_nyc_taxi series before writing this: comparing each
    # point to the same point one cycle back turns a 0.0 raw spikiness into a real signal.
    period = 24
    days = 10
    anomaly_day = 5
    anomaly_start = anomaly_day * period + 8
    anomaly_len = 5
    values = [50.0 + 40.0 * math.sin(index * 2.0 * math.pi / period) for index in range(days * period)]
    for offset in range(anomaly_len):
        values[anomaly_start + offset] -= 30.0

    profile = _extract_profile(values)

    assert profile.seasonality_strength >= 0.42
    assert profile.seasonality_dominant_lag == period
    assert profile.spikiness >= 0.2


def test_spikiness_stays_low_on_clean_seasonal_series_with_no_real_anomaly() -> None:
    # Regression guard: a purely seasonal series with no injected anomaly should not suddenly
    # read as spiky just because spikiness is now measured on a seasonal residual.
    values = [50.0 + 40.0 * math.sin(index * 2.0 * math.pi / 24.0) for index in range(240)]
    profile = _extract_profile(values)

    assert profile.seasonality_strength >= 0.42
    assert profile.spikiness < 0.2


def test_spikiness_falls_back_to_raw_values_when_series_too_short_for_a_residual() -> None:
    # Seasonality can't be trusted yet on a short series (well under 3 full cycles), so this
    # should behave exactly as before the fix - no crash, no forced residual.
    values = [50.0 + 40.0 * math.sin(index * 2.0 * math.pi / 24.0) for index in range(20)]
    profile = _extract_profile(values)

    assert profile.spikiness >= 0.0


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


def test_pyod_outlier_is_not_shape_gated_on_a_seasonal_profile() -> None:
    # nyc_taxi-shaped case: the series is labeled seasonal/repeating_pattern with no irregularity
    # label yet, but genuinely looks spiky (spikiness=0.4). Before the shape/irregularity split,
    # this shape mismatch capped pyod_outlier at PROFILE_MISMATCH_CAP (0.54) regardless of its own
    # evidence, always landing NOT_RECOMMENDED. pyod_outlier only claims irregularity profiles, so
    # a shape-only detected_profiles must not be held against it - its own scoring rules should
    # decide instead. Note the ceiling here is OPTIONAL (0.76), not RECOMMENDED (>=0.8): reaching
    # RECOMMENDED still requires profile_match (the +0.10 bonus), i.e. an irregularity label
    # actually being detected - this fix only stops the false floor, it doesn't invent a match.
    router = UniversalTimeSeriesRouter()
    decisions = {
        decision.analyzer: decision
        for decision in router.recommend_analyzers_for_profile(
            _profile(detected_profiles=["seasonal", "repeating_pattern"], spikiness=0.4, shift_index=0.0)
        )
    }

    decision = decisions["pyod_outlier"]
    assert decision.eligible is True
    assert decision.parameters_tested["profile_match"] is False
    assert decision.final_score == 0.76
    assert decision.recommendation == "OPTIONAL"


def test_an_analyzer_whose_library_is_missing_is_rejected_not_recommended() -> None:
    profile = _profile(detected_profiles=["seasonal", "repeating_pattern", "trend"])

    installed = {
        decision.analyzer: decision
        for decision in UniversalTimeSeriesRouter(missing_libraries={}).recommend_analyzers_for_profile(profile)
    }
    missing = {
        decision.analyzer: decision
        for decision in UniversalTimeSeriesRouter(missing_libraries={"prophet": "prophet"}).recommend_analyzers_for_profile(profile)
    }

    assert installed["prophet"].eligible is True
    assert installed["prophet"].recommendation != "REJECTED"
    assert missing["prophet"].eligible is False
    assert missing["prophet"].recommendation == "REJECTED"
    assert missing["prophet"].final_score == 0.0
    assert missing["prophet"].routing_reason == (
        "Prophet was rejected because the prophet library is not installed, so this analyzer does not run."
    )
    assert missing["stumpy"].recommendation == installed["stumpy"].recommendation
