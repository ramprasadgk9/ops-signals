from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from intelligence.analyzers.pyod_outlier import PyODOutlierAnalyzer


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


def test_pyod_outlier_analyzer_emits_anomaly_signal_for_outlier_series() -> None:
    values = [50.0 + (index % 5) for index in range(60)]
    values[20] = 180.0
    values[45] = 5.0

    signals = PyODOutlierAnalyzer(contamination=0.05, min_samples=50, grouping_gap="5m").analyze(_frame(values))

    assert signals
    signal = signals[0]
    assert signal.signal_type == "anomaly"
    assert signal.analyzer_id == "pyod_outlier"
    assert signal.evidence["library"] == "pyod"
    assert signal.evidence["detector"] == "KNN"
    assert signal.evidence["implementation"]["library"] == "pyod"
    assert signal.evidence["implementation"]["detector"] == "KNN"
    assert signal.evidence["implementation"]["detector_type"] == "knn"
    assert signal.evidence["contamination"] == 0.05
    assert signal.evidence["max_anomaly_score"] > 0
    assert signal.evidence["point_count"] >= 1
    assert signal.evidence["outlier_indices"]
    assert signal.evidence["outlier_timestamps"]
    assert signal.evidence["min_samples"] == 50
    assert signal.evidence["finding_rule"]["min_range_excess"] == 0.56
    assert signal.evidence["finding_rule_matched"] is True


def test_a_single_clear_spike_is_a_finding() -> None:
    # One point far outside the normal range: the case the old 8-points-per-group rule could never pass.
    values = [50.0 + (index % 5) for index in range(120)]
    values[20] = 180.0

    signals = PyODOutlierAnalyzer(contamination=0.01, min_samples=50, grouping_gap="5m").analyze(_frame(values))

    spike = next(signal for signal in signals if 20 in signal.evidence["outlier_indices"])
    assert spike.evidence["finding_rule_matched"] is True
    assert spike.evidence["range_excess"] > 20
    assert spike.confidence > 0.95


def test_the_top_one_percent_of_healthy_noise_is_not_a_finding() -> None:
    # KNN always marks its contamination share of points; on smooth noise those sit at the edge of
    # the normal range, not beyond it.
    rng = np.random.default_rng(7)
    values = list(50.0 + rng.normal(0, 1, 300))

    signals = PyODOutlierAnalyzer(contamination=0.01, min_samples=50, grouping_gap="5m").analyze(_frame(values))

    assert signals, "KNN marks outliers even on healthy data"
    assert all(signal.evidence["finding_rule_matched"] is False for signal in signals)
    assert all(signal.confidence < 0.5 for signal in signals)


def test_confidence_is_absolute_crosses_one_half_at_the_rule_and_keeps_ranking() -> None:
    analyzer = PyODOutlierAnalyzer()

    # A lone point inside the normal range: 1 of the 8 points a sustained stretch needs.
    assert analyzer._confidence(0.0) == 0.0625
    assert analyzer._confidence(0.28) == 0.25
    assert analyzer._confidence(0.56) == 0.5
    assert analyzer._confidence(1.12) == 0.75
    # No ceiling reached early: a bigger spike always ranks above a smaller one.
    assert analyzer._confidence(5.0) < analyzer._confidence(29.0) < 1.0
    # The sustained-stretch evidence is on the same scale: 0.5 at 8 points, 0.75 at 16.
    assert analyzer._confidence(0.0, points=8) == 0.5
    assert analyzer._confidence(0.0, points=16) == 0.75


def test_a_sustained_unusual_stretch_inside_the_normal_range_is_a_finding() -> None:
    # Ten unusual points in a row that never leave the normal range: no single value is a clear
    # spike, but together they change the series' shape.
    values = [50.0 + (index % 5) for index in range(200)]
    for offset in range(10):
        values[100 + offset] = 54.3 + 0.1 * offset

    signals = PyODOutlierAnalyzer(contamination=0.05, min_samples=50, grouping_gap="5m").analyze(_frame(values))

    stretch = next(signal for signal in signals if 100 in signal.evidence["outlier_indices"])
    assert stretch.evidence["point_count"] >= 8
    assert stretch.evidence["range_excess"] < 0.56
    assert stretch.evidence["finding_rule_matched"] is True


def test_pyod_outlier_analyzer_skips_short_dataset() -> None:
    signals = PyODOutlierAnalyzer(min_samples=50).analyze(_frame([1.0, 2.0, 100.0]))

    assert signals == []


def _week(values_for_day, days: int = 7) -> pd.DataFrame:
    """Five-minute readings for `days` days; values_for_day(day, slot) gives each reading (288 slots a day)."""
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    rows = [(start + timedelta(days=day, minutes=5 * slot), float(values_for_day(day, slot)))
            for day in range(days) for slot in range(288)]
    return pd.DataFrame(
        {
            "timestamp": [row[0] for row in rows],
            "value": [row[1] for row in rows],
            "metric_name": ["logins"] * len(rows),
            "service": ["web"] * len(rows),
            "env": ["prod"] * len(rows),
        }
    )


QUIET = {"compare_daily_peaks": True}


def _findings(frame: pd.DataFrame) -> list:
    """Findings in quiet mode (compare_daily_peaks on)."""
    signals = PyODOutlierAnalyzer(contamination=0.01, min_samples=50, grouping_gap="15m", finding_rule=QUIET).analyze(frame)
    return [signal for signal in signals if signal.evidence["finding_rule_matched"] and signal.confidence >= 0.5]


def _logins(day: int, slot: int) -> float:
    """About 12 logins per five minutes, rising to about 70 over the lunch hour every day."""
    rng = np.random.default_rng(day * 1000 + slot)
    lunch = 144 <= slot < 156
    return (70.0 if lunch else 12.0) + rng.normal(0, 2)


def test_a_rush_that_happens_every_day_is_not_a_finding() -> None:
    # The lunch rush is far beyond the 5th-95th range, which the range rule alone reported every day.
    lunch = [f for f in _findings(_week(_logins)) if 12 <= f.start_time.hour < 13]

    assert lunch == []


def test_a_burst_far_above_the_usual_daily_peak_is_a_finding() -> None:
    def attack(day: int, slot: int) -> float:
        return 1200.0 if (day, slot) == (5, 40) else _logins(day, slot)

    findings = sorted(_findings(_week(attack)), key=lambda f: f.confidence, reverse=True)

    assert findings[0].start_time == datetime(2026, 1, 10, 3, 20, tzinfo=timezone.utc)
    assert findings[0].evidence["daily_peaks"]["peak_ratio"] > 10
    assert findings[0].confidence > 0.9
    assert all(f.confidence < 0.6 for f in findings[1:])


def test_a_counter_at_zero_blips_to_the_same_size_every_day_but_an_outage_stands_out() -> None:
    def errors(day: int, slot: int) -> float:
        if (day, slot) == (5, 200):
            return 300.0
        return 5.0 if slot == 100 + day else 0.0

    findings = _findings(_week(errors))

    assert len(findings) == 1 and findings[0].evidence["daily_peaks"]["usual_high"] == 5.0
    assert findings[0].start_time.day == 10


def test_with_under_three_other_days_the_range_rule_decides_alone() -> None:
    signals = PyODOutlierAnalyzer(
        contamination=0.01, min_samples=50, grouping_gap="15m", finding_rule=QUIET
    ).analyze(_week(_logins, days=2))

    assert any(signal.evidence["finding_rule_matched"] for signal in signals)
    assert all(signal.evidence["daily_peaks"] is None for signal in signals)


def test_quiet_mode_is_off_by_default_so_the_rush_is_still_reported() -> None:
    signals = PyODOutlierAnalyzer(contamination=0.01, min_samples=50, grouping_gap="15m").analyze(_week(_logins))

    assert any(signal.evidence["finding_rule_matched"] for signal in signals)
    assert all(signal.evidence["daily_peaks"] is None for signal in signals)
    assert signals[0].evidence["finding_rule"]["compare_daily_peaks"] is False


def test_spikes_that_recur_on_some_days_are_still_findings() -> None:
    # A spike on three days of the week: the typical day's peak, not the second-highest, sets the bar.
    def spikes(day: int, slot: int) -> float:
        rng = np.random.default_rng(day * 1000 + slot)
        return 56.0 if day in (0, 2, 4) and slot == 150 else 38.0 + rng.normal(0, 0.2)

    days = sorted({f.start_time.day for f in _findings(_week(spikes)) if f.evidence["range_excess"] > 5})

    assert days == [5, 7, 9]
