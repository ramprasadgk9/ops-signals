from __future__ import annotations

from datetime import datetime, timezone

import pytest

from intelligence.importance_score import score_signal
from intelligence.signals.schema import OperationalSignal

AT = datetime(2026, 9, 1, 16, 40, tzinfo=timezone.utc)


def _signal(signal_type: str, analyzer_id: str, evidence: dict) -> OperationalSignal:
    return OperationalSignal(
        signal_type=signal_type,
        analyzer_id=analyzer_id,
        metric_name="cpu_usage",
        service="checkout",
        env="prod",
        severity="high",
        confidence=0.9,
        start_time=AT,
        end_time=AT,
        summary="",
        evidence=evidence,
    )


def test_a_pyod_spike_gets_credit_for_its_size() -> None:
    # QA-26: PyOD reports range_excess, not max_abs_zscore, so every PyOD spike scored zero for
    # size: a 9x spike and one just past the rule scored the same.
    huge = score_signal(_signal("anomaly", "pyod_outlier", {"range_excess": 9.29}))
    small = score_signal(_signal("anomaly", "pyod_outlier", {"range_excess": 0.6}))

    assert huge > small
    assert huge == score_signal(_signal("anomaly", "anomaly_zscore", {"max_abs_zscore": 40.0}))


def test_pyod_range_excess_is_scored_on_the_z_score_scale() -> None:
    # Its 0.56 rule is z = 3.5, so a point exactly at the rule scores like a z-score of 3.5.
    at_rule = score_signal(_signal("anomaly", "pyod_outlier", {"range_excess": 0.56}))

    assert at_rule == pytest.approx(score_signal(_signal("anomaly", "anomaly_zscore", {"max_abs_zscore": 3.4884})), abs=1e-4)


def test_a_ruptures_change_is_scored_by_its_size_like_a_baseline_shift() -> None:
    small = score_signal(_signal("ruptures", "ruptures", {"percent_change": 5.0}))
    large = score_signal(_signal("ruptures", "ruptures", {"percent_change": 80.0}))

    assert large > small
    assert large == score_signal(_signal("baseline_shift", "baseline_shift", {"percent_change": 80.0}))


def test_signals_without_a_size_keep_the_neutral_middle() -> None:
    motif = score_signal(_signal("pattern_discovery", "stumpy", {}))
    ruptures_without_size = score_signal(_signal("ruptures", "ruptures", {}))
    half_size = score_signal(_signal("baseline_shift", "baseline_shift", {"percent_change": 50.0}))

    assert motif == ruptures_without_size == half_size
