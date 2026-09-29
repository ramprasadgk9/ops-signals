from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from backend.app.analyzers.custom.seasonal_anomaly import SeasonalAnomalyAnalyzer
from backend.app.services.timeseries_routing_service import TimeSeriesRoutingService, build_csv_routing_config
from experiments.analyzer_router.feature_extractor import calendar_seasonality
from intelligence.config import load_config
from intelligence.finding_aggregator import FindingAggregator
from intelligence.importance_score import score_signals
from intelligence.normalize.normalizer import normalize_timeseries
from intelligence.pipeline import SignalPipeline

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DAY = 288  # 5-minute points per day
INTERVAL_SECONDS = 300


class NullStore:
    engine = None


def _daily_traffic(days: int = 7, seed: int = 5) -> np.ndarray:
    """~50 req/s at 3am, ~800 req/s at 3pm, every day, plus noise."""
    index = np.arange(DAY * days)
    phase = (index % DAY) / DAY
    return 425 + 375 * np.sin(2 * np.pi * (phase - 0.375)) + np.random.default_rng(seed).normal(0, 20, len(index))


def _normalized(values: np.ndarray, *, drop: range | list[int] = ()) -> pd.DataFrame:
    timestamps = pd.date_range("2026-09-01", periods=len(values), freq="5min", tz="UTC")
    frame = pd.DataFrame({"timestamp": timestamps, "metric_name": "rps", "value": values, "service": "checkout", "env": "prod"})
    config = build_csv_routing_config(provider="generic", service="checkout", metric_name="rps", interval="5m", analyzer_id="all", preview=True)
    return normalize_timeseries(frame.drop(index=list(drop)), config.input)


def _at(day: int, hour: int, minute: int = 0) -> int:
    return day * DAY + (hour * 60 + minute) // 5


# --- calendar_seasonality ---------------------------------------------------------------------


def test_calendar_seasonality_finds_a_smooth_daily_cycle() -> None:
    strength, lag = calendar_seasonality(_daily_traffic(), INTERVAL_SECONDS)

    assert lag == DAY
    assert strength > 0.9


def test_calendar_seasonality_ignores_noise_random_walks_and_level_shifts() -> None:
    rng = np.random.default_rng(1)
    size = DAY * 7
    noise = 50 + rng.normal(0, 3, size)
    random_walk = 50 + np.cumsum(rng.normal(0, 0.5, size))
    level_shift = np.where(np.arange(size) < size // 2, 40.0, 70.0) + rng.normal(0, 2, size)

    for values in (noise, random_walk, level_shift):
        strength, _ = calendar_seasonality(values, INTERVAL_SECONDS)
        assert strength < 0.2


def test_calendar_seasonality_needs_three_cycles_and_a_whole_number_of_points_per_day() -> None:
    assert calendar_seasonality(_daily_traffic(days=2), INTERVAL_SECONDS) == (0.0, None)
    assert calendar_seasonality(_daily_traffic(), 7 * 60) == (0.0, None)
    assert calendar_seasonality(_daily_traffic(), None) == (0.0, None)


# --- SeasonalAnomalyAnalyzer --------------------------------------------------------------------


def test_off_hours_spike_at_a_daytime_level_is_flagged() -> None:
    values = _daily_traffic()
    spike = _at(6, 3)
    values[spike : spike + 4] = 400.0

    [signal] = SeasonalAnomalyAnalyzer().analyze(_normalized(values))

    assert signal.signal_type == "anomaly"
    assert signal.analyzer_id == "seasonal_anomaly"
    assert signal.severity == "high"
    assert signal.evidence["direction"] == "above"
    assert signal.evidence["anomalous_points"] == 4
    assert signal.evidence["period_points"] == DAY
    assert signal.evidence["expected_value"] < 100
    assert "daily cycle" in signal.summary
    assert "x the usual level" in signal.summary


def test_daytime_drop_is_flagged_below_expected() -> None:
    values = _daily_traffic()
    outage = _at(6, 15)
    values[outage : outage + 6] = 150.0

    [signal] = SeasonalAnomalyAnalyzer().analyze(_normalized(values))

    assert signal.evidence["direction"] == "below"
    assert signal.evidence["expected_value"] > 600


def test_normal_daily_peaks_and_troughs_are_not_flagged() -> None:
    assert SeasonalAnomalyAnalyzer().analyze(_normalized(_daily_traffic())) == []


def test_non_seasonal_or_too_short_series_are_left_alone() -> None:
    rng = np.random.default_rng(2)
    spiky_noise = 50 + rng.normal(0, 3, DAY * 7)
    spiky_noise[[300, 900, 1500]] = 95.0
    two_days = _daily_traffic(days=2)
    two_days[_at(1, 3)] = 400.0

    assert SeasonalAnomalyAnalyzer().analyze(_normalized(spiky_noise)) == []
    assert SeasonalAnomalyAnalyzer().analyze(_normalized(two_days)) == []


def test_empty_time_buckets_are_never_reported_as_anomalies() -> None:
    normalized = _normalized(_daily_traffic(), drop=range(_at(4, 10), _at(4, 10) + 6))

    assert normalized["value"].isna().sum() == 6
    assert SeasonalAnomalyAnalyzer().analyze(normalized) == []


def test_signal_becomes_an_unusual_activity_finding() -> None:
    values = _daily_traffic()
    values[_at(6, 3) : _at(6, 3) + 4] = 400.0
    normalized = _normalized(values)
    signals = score_signals(SeasonalAnomalyAnalyzer().analyze(normalized), normalized["timestamp"].max().to_pydatetime())

    [finding] = FindingAggregator().aggregate(signals, normalized).findings

    assert finding.category == "unusual_activity"
    assert finding.title == "rps has unusual activity in the selected time window."


# --- Routing ------------------------------------------------------------------------------------


def _routing(values: np.ndarray) -> list[dict[str, object]]:
    return TimeSeriesRoutingService().route_normalized(_normalized(values)).analyzer_routing


def test_router_no_longer_picks_it_even_on_a_strong_daily_cycle() -> None:
    # Retired from routing (see config/analyzer_registry.d/custom_seasonal_anomaly.yml): the router
    # has no decision for it, so it never takes the slot that pyod_outlier used to lose to it.
    routing = _routing(_daily_traffic())
    config = load_config(PROJECT_ROOT / "config.yaml")
    config.analysis.selection_mode = "recommended_threshold"
    config.analysis.recommendation_execution.min_score = 0.8
    config.analysis.recommendation_execution.max_analyzers = 3

    allowed = SignalPipeline(config=config, store=NullStore())._allowed_pipeline_analyzers(routing)

    assert all(d["analyzer_id"] != "seasonal_anomaly" for d in routing)
    assert "seasonal_anomaly" not in allowed
