from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from intelligence.analyzers.trend import TrendAnalyzer


def _frame(values: list[float]) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=index) for index in range(len(values))],
            "value": values,
            "metric_name": ["cpu_usage"] * len(values),
            "service": ["checkout"] * len(values),
            "env": ["prod"] * len(values),
        }
    )


def test_trend_analyzer_emits_finding_rule_metadata() -> None:
    values = [100.0 + index for index in range(30)]

    signals = TrendAnalyzer(
        min_slope_percent=10,
        finding_rules={"min_slope_percent": 20},
        implementation={"library": "statsmodels", "model": "OLS"},
    ).analyze(_frame(values))

    assert signals
    signal = signals[0]
    assert signal.signal_type == "trend"
    assert signal.evidence["slope_percent"] >= 20
    assert signal.evidence["finding_rules"]["min_slope_percent"] == 20
    assert signal.evidence["finding_rule_matched"] is True
    assert signal.evidence["implementation"] == {"library": "statsmodels", "model": "OLS"}


def test_trend_analyzer_suppresses_signals_below_finding_rule() -> None:
    values = [100.0 + index * 0.1 for index in range(30)]

    signals = TrendAnalyzer(
        min_slope_percent=1,
        finding_rules={"min_slope_percent": 10},
    ).analyze(_frame(values))

    assert signals == []


def _daily_cycle(start_hour: int, drift_percent: float = 0.0, days: int = 7) -> pd.DataFrame:
    # A request-rate-like metric: averages 100, swings +/-50 over each day, plus a steady drift of
    # drift_percent of the average level across the window.
    timestamps = pd.date_range("2026-01-01", periods=days * 288, freq="5min", tz="UTC") + pd.Timedelta(hours=start_hour)
    hours = (timestamps.hour + timestamps.minute / 60).to_numpy()
    values = 100 + 50 * np.sin(2 * np.pi * hours / 24) + np.linspace(0, drift_percent, len(timestamps))
    return pd.DataFrame(
        {"timestamp": timestamps, "value": values, "metric_name": "requests", "service": "checkout", "env": "prod"}
    )


@pytest.mark.parametrize("start_hour", [0, 6, 12, 18])
def test_daily_cycle_without_drift_is_not_a_trend_whatever_hour_the_window_starts(start_hour: int) -> None:
    # A straight line through every point read this as +14%, -34% or +36% depending on the hour.
    assert TrendAnalyzer(min_slope_percent=10).analyze(_daily_cycle(start_hour)) == []


@pytest.mark.parametrize("start_hour", [0, 6, 12, 18])
def test_real_drift_under_a_daily_cycle_is_measured_through_daily_means(start_hour: int) -> None:
    [signal] = TrendAnalyzer(min_slope_percent=10).analyze(_daily_cycle(start_hour, drift_percent=15.0))

    assert signal.evidence["fit"] == "daily_means"
    assert signal.evidence["slope"] > 0
    assert "upward" in signal.summary
    assert 12.0 <= signal.evidence["slope_percent"] <= 16.0


def test_short_window_fits_every_point_relative_to_the_window_average() -> None:
    values = [100.0 + index for index in range(30)]

    [signal] = TrendAnalyzer(min_slope_percent=10).analyze(_frame(values))

    assert signal.evidence["fit"] == "points"
    assert signal.evidence["slope_percent"] == pytest.approx(29 / 114.5 * 100, abs=0.01)


def test_only_ols_is_fitted_and_another_model_is_reported_as_ignored(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        analyzer = TrendAnalyzer(implementation={"library": "statsmodels", "model": "RLM"})

    assert analyzer.model == "OLS"
    assert "ignoring implementation.model='RLM'" in caplog.text
