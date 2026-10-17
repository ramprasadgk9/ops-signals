from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from intelligence.finding_aggregator import FindingAggregator
from intelligence.signals.schema import OperationalSignal

BASE_TIME = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _points() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": [BASE_TIME + timedelta(minutes=5 * index) for index in range(288)],
            "metric_name": "cpu_usage",
            "service": "checkout",
            "value": [95.0 if index == 200 else 50.0 for index in range(288)],
        }
    )


def _pyod(signal_id: str, minutes: int, range_excess: float, matched: bool, importance: float) -> OperationalSignal:
    start = BASE_TIME + timedelta(minutes=minutes)
    return OperationalSignal(
        signal_type="anomaly",
        analyzer_id="pyod_outlier",
        metric_name="cpu_usage",
        service="checkout",
        env="prod",
        severity="medium",
        confidence=0.5,
        start_time=start,
        end_time=start,
        summary=f"cpu_usage produced 1 pyod outlier point(s), reaching {range_excess:.2f}x its normal range.",
        evidence={"range_excess": range_excess, "finding_rule_matched": matched},
        signal_id=signal_id,
        importance_score=importance,
    )


def test_the_summary_and_timing_come_from_the_spike_not_the_noise_around_it() -> None:
    # QA-02: one real 9x spike between two sub-threshold points. The finding used to attach all
    # three and lead with the first: "0.28x its normal range".
    early_noise = _pyod("noise-early", 300, 0.28, matched=False, importance=0.30)
    spike = _pyod("spike", 1000, 9.29, matched=True, importance=0.60)
    late_noise = _pyod("noise-late", 1400, 0.51, matched=False, importance=0.35)

    findings = FindingAggregator().aggregate([early_noise, spike, late_noise], _points()).findings

    assert len(findings) == 1
    finding = findings[0]
    assert finding.signal_ids == ["spike"]
    assert "9.29x" in finding.summary
    assert "0.28x" not in finding.summary
    assert "1 anomaly window(s)" in finding.summary
    assert finding.event_start == spike.start_time


def test_noise_attached_to_a_structural_change_no_longer_moves_its_start_time() -> None:
    ruptures = OperationalSignal(
        signal_type="ruptures",
        analyzer_id="ruptures",
        metric_name="cpu_usage",
        service="checkout",
        env="prod",
        severity="high",
        confidence=0.9,
        start_time=BASE_TIME + timedelta(minutes=500),
        end_time=BASE_TIME + timedelta(minutes=900),
        summary="A structural change was detected.",
        evidence={"change_point_time": (BASE_TIME + timedelta(minutes=500)).isoformat()},
        signal_id="ruptures",
        importance_score=0.7,
    )
    late_noise = _pyod("noise", 1400, 0.10, matched=False, importance=0.2)

    finding = FindingAggregator().aggregate([ruptures, late_noise], _points()).findings[0]

    assert finding.signal_ids == ["ruptures"]
    assert finding.event_start == ruptures.start_time


def test_the_strongest_matched_anomaly_leads_when_there_are_several() -> None:
    small = _pyod("small", 300, 0.9, matched=True, importance=0.40)
    big = _pyod("big", 1000, 7.5, matched=True, importance=0.70)

    finding = FindingAggregator().aggregate([small, big], _points()).findings[0]

    assert finding.summary.startswith("Cpu_usage produced 1 pyod outlier point(s), reaching 7.50x")
    assert finding.signal_ids == ["small", "big"]


def test_a_group_of_only_noise_is_still_not_a_finding() -> None:
    noise = [_pyod("a", 300, 0.2, matched=False, importance=0.3), _pyod("b", 900, 0.3, matched=False, importance=0.3)]

    assert FindingAggregator().aggregate(noise, _points()).findings == []
