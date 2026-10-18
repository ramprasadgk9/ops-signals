from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from intelligence.analyzers.anomaly_zscore import ZScoreAnomalyAnalyzer


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


def test_zscore_analyzer_emits_implementation_and_finding_rule_metadata() -> None:
    values = [50.0] * 40 + [120.0]

    signals = ZScoreAnomalyAnalyzer(
        implementation={"library": "pandas", "method": "zscore", "zscore_threshold": 3.0, "grouping_gap": "15m"},
        finding_rules={"min_abs_zscore": 3.0, "min_points": 1},
    ).analyze(_frame(values))

    assert signals
    signal = signals[0]
    assert signal.analyzer_id == "anomaly_zscore"
    assert signal.evidence["implementation"]["library"] == "pandas"
    assert signal.evidence["implementation"]["method"] == "zscore"
    assert signal.evidence["finding_rules"] == {"min_abs_zscore": 3.0, "min_points": 1}
    assert signal.evidence["finding_rule_matched"] is True


def test_zscore_analyzer_marks_finding_rule_unmatched_when_group_too_small() -> None:
    values = [50.0] * 40 + [120.0]

    signals = ZScoreAnomalyAnalyzer(
        zscore_threshold=3.0,
        grouping_gap="15m",
        finding_rules={"min_abs_zscore": 3.0, "min_points": 2},
    ).analyze(_frame(values))

    assert signals
    assert signals[0].evidence["finding_rule_matched"] is False


def test_zscore_analyzer_does_not_repeatedly_flag_a_stable_new_baseline() -> None:
    # 90 points at the old level, then a permanent shift to a new, stable level.
    # Pre-fix, every post-shift point would be flagged against the stale blended
    # mean/std for as long as the shift stays in the window. Post-fix, the
    # analyzer re-baselines on the post-shift segment and finds nothing unusual.
    values = [30.0] * 90 + [90.0, 90.0, 90.0, 90.0, 91.0]

    signals = ZScoreAnomalyAnalyzer().analyze(_frame(values))

    assert signals == []


def test_zscore_analyzer_rebaselines_and_still_catches_a_real_anomaly() -> None:
    # Same permanent shift as above, but one genuine spike rides on top of the
    # new, otherwise-stable baseline. Only the spike should be flagged - not
    # the whole post-shift plateau - and evidence should record the rebaseline.
    post_shift = [90.0] * 16 + [500.0] + [90.0]
    values = [30.0] * 90 + post_shift

    signals = ZScoreAnomalyAnalyzer().analyze(_frame(values))

    assert len(signals) == 1
    signal = signals[0]
    assert signal.evidence["rebaselined_after_change_point"] is True
    assert signal.evidence["change_point_index"] == 90
    assert signal.evidence["point_count"] == 1
    assert signal.start_time == signal.end_time


def test_zscore_analyzer_walks_past_a_noisy_transition_to_the_settled_baseline() -> None:
    # A single change point can land inside a still-noisy transition rather than
    # at its true start (found against real NAB EC2 CPU data: a breakpoint landed
    # mid-recovery, and rebaselining against that noisy segment - std inflated by
    # the transition itself - masked the very deviation it should have judged
    # against). The analyzer should keep walking forward until it finds where the
    # series actually settled, not stop at the first, still-turbulent split.
    baseline = [50.0] * 60
    noisy_transition = [20.0, 80.0] * 10
    settled_baseline = [90.0] * 19 + [91.0]
    values = baseline + noisy_transition + settled_baseline

    signals = ZScoreAnomalyAnalyzer().analyze(_frame(values))

    assert len(signals) == 1
    signal = signals[0]
    assert signal.evidence["rebaselined_after_change_point"] is True
    # The true settle point is at index 80 (end of the noisy transition) - not
    # index 60 (its start), which is what a single, non-recursive check would
    # have landed on.
    assert signal.evidence["change_point_index"] == 80
    assert signal.evidence["point_count"] == 1


def test_zscore_analyzer_falls_back_to_full_window_when_post_shift_segment_is_short() -> None:
    # The shift is real, but only 3 points follow it - too few to trust a fresh
    # baseline (below rebaseline.min_segment_size=5), so this should behave
    # exactly like the pre-fix, whole-window calculation.
    values = [50.0] * 40 + [200.0, 200.0, 200.0]

    signals = ZScoreAnomalyAnalyzer().analyze(_frame(values))

    assert signals
    assert signals[0].evidence["rebaselined_after_change_point"] is False
    assert "change_point_index" not in signals[0].evidence


def test_zscore_analyzer_flags_a_spike_on_the_last_points_instead_of_rebaselining_onto_it() -> None:
    # QA-31: the spike itself looked like a change point 8 points from the end, and in 8 points no
    # reading can reach z 3, so a 30-sigma last reading went unreported.
    noise = [50.0, 51.2, 49.1, 50.6, 48.8, 50.3, 51.7, 49.4, 50.9, 49.8]
    for from_end in (1, 2, 3):
        values = noise * 28
        values[-from_end] = 95.0

        signals = ZScoreAnomalyAnalyzer().analyze(_frame(values))

        assert len(signals) == 1, from_end
        assert signals[0].evidence["max_abs_zscore"] > 10
        assert signals[0].evidence["rebaselined_after_change_point"] is False


def test_zscore_analyzer_still_rebaselines_onto_a_short_but_genuine_new_level() -> None:
    # The short tail is a real new level (every point moved), not an outlier at the old level.
    values = [50.0, 51.2, 49.1, 50.6, 48.8, 50.3, 51.7, 49.4, 50.9, 49.8] * 20 + [90.0, 90.5, 89.6, 90.2, 89.9, 90.4, 90.1, 89.7]

    assert ZScoreAnomalyAnalyzer().analyze(_frame(values)) == []


def _quiet_day(outliers: dict[int, float]) -> list[float]:
    """288 five-minute readings alternating 49/51 (standard deviation 1), with the given points set."""
    values = [49.0 if index % 2 else 51.0 for index in range(288)]
    for index, value in outliers.items():
        values[index] = value
    return values


def test_zscore_analyzer_does_not_turn_one_chance_point_on_a_long_quiet_series_into_a_finding() -> None:
    # QA-43: in 288 normal readings about 0.8 land beyond |z| 3 by chance, so one point at z 3.06
    # is noise. It stays a signal (labs still show it) but is not a finding.
    signals = ZScoreAnomalyAnalyzer().analyze(_frame(_quiet_day({100: 53.1})))

    assert len(signals) == 1
    assert 3.0 <= signals[0].evidence["max_abs_zscore"] < 3.13
    assert signals[0].evidence["finding_rule_matched"] is False


def test_zscore_analyzer_still_finds_a_clear_spike_on_a_long_series() -> None:
    signals = ZScoreAnomalyAnalyzer().analyze(_frame(_quiet_day({100: 70.0})))

    assert len(signals) == 1
    assert signals[0].evidence["finding_rule_matched"] is True


def test_zscore_analyzer_still_finds_two_neighbouring_points_just_past_the_threshold() -> None:
    # Two readings beyond |z| 3 within the grouping gap are rare by chance, unlike one.
    signals = ZScoreAnomalyAnalyzer().analyze(_frame(_quiet_day({100: 53.3, 101: 53.3})))

    assert len(signals) == 1
    assert signals[0].evidence["point_count"] == 2
    assert signals[0].evidence["finding_rule_matched"] is True
