"""The "too little data to check" rule the Autonomous Monitoring page counts must be the router's own."""

from experiments.analyzer_router.analyzer_registry import AnalyzerCapability
from experiments.analyzer_router.eligibility import MAX_MISSING_PERCENTAGE, MIN_VALID_SAMPLES, evaluate_eligibility, too_little_data_to_check
import numpy as np
import pandas as pd

from experiments.analyzer_router.feature_extractor import extract_series_profile

CHANGE_ANALYZER = AnalyzerCapability(analyzer="ruptures", display_name="Ruptures", eligibility_rules={"min_samples": 30, "requires_numeric": True})


def _profile(missing_every: int | None):
    """1,441 one-minute readings (24 h); with missing_every=k, k-1 of every k are blank in the
    first half - the shape of Prometheus asleep overnight, then back."""
    timestamps = pd.date_range("2026-11-12T22:00:00Z", periods=1441, freq="1min")
    values = 100 + np.sin(np.arange(1441) / 30.0) * 5
    if missing_every:
        values = values.astype(float)
        first_half = np.arange(1441) < 1000
        values[first_half & (np.arange(1441) % missing_every != 0)] = np.nan
    frame = pd.DataFrame({"timestamp": timestamps, "value": values})
    _, profile, _ = extract_series_profile(frame, "timestamp", "value", interpolation_enabled=False)
    return profile


def test_limits_are_at_most_30_percent_missing_and_at_least_30_readings() -> None:
    assert (MAX_MISSING_PERCENTAGE, MIN_VALID_SAMPLES) == (30.0, 30)
    assert too_little_data_to_check(30.0, 30) is False
    assert too_little_data_to_check(30.1, 1000) is True
    assert too_little_data_to_check(0.0, 29) is True
    assert too_little_data_to_check(None, None) is True


def test_a_series_mostly_missing_is_too_little_for_change_analyzers_and_the_rule_agrees() -> None:
    profile = _profile(missing_every=3)
    assert profile.missing_percentage > MAX_MISSING_PERCENTAGE
    assert too_little_data_to_check(profile.missing_percentage, profile.valid_sample_count) is True
    assert evaluate_eligibility(CHANGE_ANALYZER, profile).eligible is False


def test_a_complete_series_is_checked_and_the_rule_agrees() -> None:
    profile = _profile(missing_every=None)
    assert too_little_data_to_check(profile.missing_percentage, profile.valid_sample_count) is False
    assert evaluate_eligibility(CHANGE_ANALYZER, profile).eligible is True
