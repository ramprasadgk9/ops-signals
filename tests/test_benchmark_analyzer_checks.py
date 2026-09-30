from __future__ import annotations

from benchmark.analyzer_checks import EXTRA_CONTROLS, TARGETS, _signals


def test_stumpy_reports_a_day_shifted_out_of_its_daily_pattern() -> None:
    (case, kinds), = TARGETS["stumpy"]

    seen, _ = _signals("stumpy", case)

    assert any(signal.signal_type in kinds for signal in seen)


def test_stumpy_stays_quiet_on_a_regular_daily_pattern() -> None:
    (case,) = EXTRA_CONTROLS["stumpy"]

    seen, _ = _signals("stumpy", case)

    assert seen == []
