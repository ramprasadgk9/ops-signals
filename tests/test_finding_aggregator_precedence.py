from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from intelligence.finding_aggregator import FindingAggregator
from intelligence.signals.schema import OperationalSignal


BASE_TIME = datetime(2026, 7, 31, 2, 25, tzinfo=timezone.utc)


def _points() -> pd.DataFrame:
    values = [0.28, 0.29, 0.27, 0.71, 0.72, 0.70]
    return pd.DataFrame(
        {
            "timestamp": [BASE_TIME + timedelta(minutes=index) for index in range(len(values))],
            "metric_name": ["cpu_usage"] * len(values),
            "service": ["checkout"] * len(values),
            "env": ["local"] * len(values),
            "value": values,
        }
    )


def _signal(signal_type: str, analyzer_id: str | None = None, summary: str | None = None, evidence: dict | None = None) -> OperationalSignal:
    analyzer_id = analyzer_id or signal_type
    return OperationalSignal(
        signal_type=signal_type,
        analyzer_id=analyzer_id,
        metric_name="cpu_usage",
        service="checkout",
        env="local",
        severity="high",
        confidence=0.9,
        start_time=BASE_TIME,
        end_time=BASE_TIME + timedelta(minutes=5),
        summary=summary or f"cpu_usage {signal_type} signal",
        evidence=evidence or {},
        signal_id=f"sig-{signal_type}-{analyzer_id}",
    )


def _finding(signals: list[OperationalSignal], profile: dict | None = None):
    result = FindingAggregator().aggregate(signals, _points(), series_profile=profile)
    assert len(result.findings) == 1
    return result.findings[0]


def test_ruptures_and_trend_prioritizes_structural_change() -> None:
    ruptures = _signal(
        "ruptures",
        summary="cpu_usage showed a persistent baseline shift of 154.7% around sample 13.",
        evidence={"change_point_index": 13, "left_mean": 0.2801, "right_mean": 0.7133, "percent_change": 154.6747},
    )
    baseline = _signal(
        "baseline_shift",
        summary="cpu_usage baseline shifted by 106.7% between the first and second half.",
        evidence={"percent_change": 106.6568},
    )
    trend = _signal(
        "trend",
        analyzer_id="trend",
        summary="cpu_usage shows a sustained upward trend of 174.0% across the batch window.",
        evidence={"slope": 0.015733, "slope_percent": 174.0396},
    )

    finding = _finding([baseline, ruptures, trend], {"detected_profiles": ["baseline_shift", "regime_change", "trend"]})

    assert finding.title == "cpu_usage experienced a persistent baseline shift during the selected time window."
    assert "structural change was detected around sample 13" in finding.summary.lower()
    assert "from 0.2801 to 0.7133" in finding.summary
    assert "154.7%" in finding.summary
    assert "106.7%" not in finding.summary
    assert "baseline shift supports this structural finding" in finding.summary
    assert "Trend Regression observed an overall upward direction" in finding.summary
    assert "sustained upward trend of 174.0%" not in finding.summary
    assert finding.signal_ids == [baseline.signal_id, ruptures.signal_id, trend.signal_id]


def test_baseline_shift_and_trend_keeps_baseline_primary() -> None:
    baseline = _signal("baseline_shift", evidence={"percent_change": -42.5})
    trend = _signal("trend", analyzer_id="trend", summary="cpu_usage shows a sustained downward trend of -50.0%.", evidence={"slope": -0.1})

    finding = _finding([baseline, trend], {"detected_profiles": ["baseline_shift", "trend"]})

    assert finding.title == "cpu_usage moved to a new baseline."
    assert finding.summary.startswith("Baseline decreased 42.5%")
    assert "secondary context" in finding.summary
    assert "sustained downward trend" not in finding.summary
    assert finding.signal_ids == [baseline.signal_id, trend.signal_id]


def test_trend_only_uses_trend_narrative() -> None:
    trend = _signal("trend", analyzer_id="trend", summary="cpu_usage shows a sustained upward trend of 25.0% across the batch window.")

    finding = _finding([trend], {"detected_profiles": ["trend"]})

    assert finding.title == "cpu_usage is trending in one direction."
    assert "sustained upward trend of 25.0%" in finding.summary


def test_ruptures_only_uses_ruptures_when_profile_is_structural() -> None:
    ruptures = _signal(
        "ruptures",
        evidence={"change_point_index": 4, "left_mean": 0.2, "right_mean": 0.5, "percent_change": 150.0},
    )

    finding = _finding([ruptures], {"detected_profiles": ["regime_change"]})

    assert finding.title == "cpu_usage experienced a persistent baseline shift during the selected time window."
    assert "structural change was detected around sample 4" in finding.summary.lower()
    assert finding.signal_ids == [ruptures.signal_id]


def test_anomaly_and_trend_keeps_anomaly_primary() -> None:
    anomaly = _signal("anomaly", summary="cpu_usage had 2 high outlier windows.")
    trend = _signal("trend", analyzer_id="trend", summary="cpu_usage shows a sustained upward trend of 20.0%.", evidence={"slope": 0.1})

    finding = _finding([anomaly, trend], {"detected_profiles": ["anomaly", "trend"]})

    assert finding.title == "cpu_usage has unusual activity in the selected time window."
    assert finding.summary.startswith("Cpu_usage had 2 high outlier windows.")
    assert "secondary context" in finding.summary
    assert "sustained upward trend" not in finding.summary
    assert finding.signal_ids == [anomaly.signal_id, trend.signal_id]


def test_seasonality_and_forecast_use_forecastable_narrative() -> None:
    seasonal = _signal("seasonality", analyzer_id="stumpy", summary="cpu_usage repeats a regular seasonal pattern.")
    forecast = _signal("forecast", analyzer_id="prophet", summary="cpu_usage has a forecastable recurring pattern.")

    finding = _finding([seasonal, forecast], {"detected_profiles": ["seasonal"]})

    assert finding.title == "cpu_usage shows predictable recurring or forecastable behaviour."
    assert "regular seasonal pattern" in finding.summary
    assert "forecastable recurring pattern" in finding.summary
    assert finding.signal_ids == [seasonal.signal_id, forecast.signal_id]
