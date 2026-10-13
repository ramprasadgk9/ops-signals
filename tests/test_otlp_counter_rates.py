"""OTLP counters become per-second rates before analysis (backend/app/otlp/rates.py). Analyzed
as raw running totals, every counter looked like a one-way trend."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.otlp.converter import OtlpPoint
from backend.app.otlp.rates import CounterRates

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _point(seconds: int, value: float, *, metric_type: str = "counter", cumulative: bool = True, start: datetime | None = START, state: str = "user") -> OtlpPoint:
    return OtlpPoint(
        metric_name="system.cpu.time",
        metric_type=metric_type,
        timestamp=START + timedelta(seconds=seconds),
        value=value,
        service="host",
        env=None,
        host=None,
        namespace=None,
        pod=None,
        attributes={"state": state},
        cumulative=cumulative,
        start_time=start,
    )


def test_a_running_total_becomes_its_growth_per_second() -> None:
    rates = CounterRates()

    first = rates.convert([_point(15, 100.0)])
    later = rates.convert([_point(30, 130.0), _point(45, 130.0)])

    assert first == []  # nothing to compare with yet
    assert [point.value for point in later] == [2.0, 0.0]


def test_each_series_keeps_its_own_previous_point() -> None:
    rates = CounterRates()
    rates.convert([_point(15, 100.0, state="user"), _point(15, 5.0, state="system")])

    out = rates.convert([_point(30, 115.0, state="user"), _point(30, 20.0, state="system")])

    assert {point.attributes["state"]: point.value for point in out} == {"user": 1.0, "system": 1.0}


def test_a_restarted_counter_counts_from_zero() -> None:
    rates = CounterRates()
    rates.convert([_point(15, 500.0)])

    dropped = rates.convert([_point(30, 30.0)])
    restarted = rates.convert([_point(45, 60.0, start=START + timedelta(seconds=40))])

    assert [point.value for point in dropped] == [2.0]  # value went down: a reset
    assert [point.value for point in restarted] == [4.0]  # new start time: a reset


def test_a_repeated_or_older_point_is_dropped() -> None:
    rates = CounterRates()
    rates.convert([_point(30, 100.0)])

    assert rates.convert([_point(30, 100.0), _point(15, 90.0)]) == []


def test_a_delta_count_is_divided_by_its_interval_and_gauges_pass_through() -> None:
    rates = CounterRates()
    delta = _point(10, 30.0, cumulative=False, start=START)
    gauge = _point(10, 87.5, metric_type="gauge", cumulative=False, start=None)

    out = rates.convert([delta, gauge])

    assert [point.value for point in out] == [3.0, 87.5]
