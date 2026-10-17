"""QA-08: the window-comparison sentence contradicted the numbers. A falling trend (70 to 41) was
"broadly consistent" while the mirrored rise "differed significantly", and a flat series with one
spike "differed significantly" at a 0.8% change in its average, with no hint the spike was why."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd

from intelligence.window_compare import compare_windows


def _points(values) -> pd.DataFrame:
    return pd.DataFrame(
        {"timestamp": pd.date_range("2026-10-01", periods=len(values), freq="5min", tz="UTC"), "value": values}
    )


def _anomaly_at(points: pd.DataFrame, index: int) -> SimpleNamespace:
    at = points["timestamp"].iloc[index].to_pydatetime()
    return SimpleNamespace(signal_type="anomaly", start_time=at, end_time=at + timedelta(minutes=5))


def test_a_fall_and_the_mirrored_rise_are_judged_the_same() -> None:
    falling = compare_windows(_points(np.linspace(70, 41, 288)))
    rising = compare_windows(_points(np.linspace(41, 70, 288)))

    assert falling["new_behavior"] is rising["new_behavior"] is True
    assert "average is 23.2% lower (from 62.78 to 48.22)" in falling["summary"]
    assert "average is 30.2% higher (from 48.22 to 62.78)" in rising["summary"]
    # The evidence number the importance score reads is unchanged.
    previous, current = falling["previous_mean"], falling["current_mean"]
    assert abs(falling["change_percent"] - (current - previous) / previous * 100.0) < 0.001


def test_a_spike_is_named_as_the_difference_not_the_level() -> None:
    values = np.full(288, 50.0)
    values[200] = 95.0
    points = _points(values)

    comparison = compare_windows(points, [_anomaly_at(points, 200)])

    assert comparison["new_behavior"] is True
    assert comparison["summary"] == "The second half of the selected time window differs from the first: it has 1 more anomaly."
    assert "average" not in comparison["summary"]


def test_a_steady_window_is_described_with_its_numbers() -> None:
    comparison = compare_windows(_points(np.full(100, 40.0) + np.tile([0.0, 1.0], 50)))

    assert comparison["new_behavior"] is False
    assert comparison["summary"] == (
        "The first and second half of the selected time window are broadly similar (average from 40.5 to 40.5, +0.0%)."
    )


def test_a_metric_starting_from_zero_counts_as_changed() -> None:
    comparison = compare_windows(_points([0.0] * 50 + [10.0] * 50))

    assert comparison["new_behavior"] is True
    assert "higher" in comparison["summary"]
