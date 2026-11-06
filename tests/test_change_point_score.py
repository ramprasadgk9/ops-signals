from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from intelligence.analyzers.baseline_shift import BaselineShiftAnalyzer
from intelligence.analyzers.ruptures import RupturesAnalyzer, detect_primary_change_point

THRESHOLD = 1.5


def _score(values) -> float:
    result = detect_primary_change_point(np.asarray(values, dtype=float), min_segment_size=5, change_threshold=0.0)
    assert result is not None
    return float(result["score"])


def _frame(values) -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01", periods=len(values), freq="5min", tz="UTC")
    return pd.DataFrame({"timestamp": timestamps, "value": values, "metric_name": "latency_ms", "service": "checkout", "env": "prod"})


def test_a_step_is_measured_against_the_noise_on_each_side_not_the_whole_series() -> None:
    # Latency bounces about 1.4 ms around 50, then about 1.4 ms around 53. The whole series'
    # spread (2.06) holds the 3 ms step itself, which scored 1.46 and missed the bar.
    before = [48, 52, 49, 51, 50]
    after = [52, 54, 53, 51, 55]

    assert _score(before + after) == pytest.approx(3 / np.sqrt(2), rel=1e-6)
    assert _score(before + after) >= THRESHOLD


def test_a_bigger_step_scores_higher() -> None:
    # Scored against the whole series' spread, a step halfway through could never pass 2:
    # 50 -> 54 and 50 -> 500 both scored 1.99.
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 2, 288)
    small = np.r_[np.full(144, 50.0), np.full(144, 54.0)] + noise
    large = np.r_[np.full(144, 50.0), np.full(144, 500.0)] + noise

    assert _score(large) > 50 * _score(small)


def test_a_two_sigma_level_shift_is_found_by_ruptures_and_baseline_shift() -> None:
    # Issue #76: 288 points of N(50, 2) stepping to 54 at point 144 gave no finding.
    rng = np.random.default_rng(0)
    values = np.r_[rng.normal(50, 2, 144), rng.normal(54, 2, 144)]

    ruptures = RupturesAnalyzer(min_segment_size=5, change_threshold=THRESHOLD).analyze(_frame(values))
    assert len(ruptures) == 1
    assert ruptures[0].evidence["change_point_index"] == pytest.approx(144, abs=5)
    # Baseline Shift's own percent rule still decides (the step is 8%): only the score changed.
    assert BaselineShiftAnalyzer(threshold_percent=25, change_threshold=THRESHOLD).analyze(_frame(values)) == []
    assert len(BaselineShiftAnalyzer(threshold_percent=5, change_threshold=THRESHOLD).analyze(_frame(values))) == 1


@pytest.mark.parametrize("seed", range(20))
def test_healthy_noise_still_has_no_change_point(seed: int) -> None:
    values = np.random.default_rng(seed).normal(50, 2, 288)

    assert RupturesAnalyzer(min_segment_size=5, change_threshold=THRESHOLD).analyze(_frame(values)) == []


def test_two_flat_levels_score_as_a_clear_change() -> None:
    values = [50.0] * 10 + [54.0] * 10

    assert _score(values) > 1e6
    signals = RupturesAnalyzer(min_segment_size=5, change_threshold=THRESHOLD).analyze(_frame(values))
    assert len(signals) == 1
    assert signals[0].confidence == 1.0
