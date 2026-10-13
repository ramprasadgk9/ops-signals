"""Turns OTLP counters into per-second rates before they are stored, as the Prometheus source does
with rate(). A counter's raw value is a running total that only goes up, so analyzed as-is every
counter looks like a trend; what matters is how fast it grows.

A cumulative counter needs its previous point, kept here in memory per series. In-process only,
matching the single-backend-instance assumption (backend/app/autonomous/scheduler.py): after a
restart each series' first point is only remembered, not stored. Series are bounded by the
cardinality cap (limits.py), which runs before this.
"""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime

from backend.app.otlp.converter import OtlpPoint

_SeriesKey = tuple[str, str, frozenset[tuple[str, str]]]


class CounterRates:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # series -> (timestamp, value, start_time) of its latest point
        self._last: dict[_SeriesKey, tuple[datetime, float, datetime | None]] = {}

    def convert(self, points: list[OtlpPoint]) -> list[OtlpPoint]:
        """Gauges pass through; counters come back as per-second rates. A cumulative counter's
        first point (nothing to compare with) and any point not newer than the last are dropped."""
        out: list[OtlpPoint] = []
        for point in sorted(points, key=lambda item: item.timestamp):
            if point.metric_type != "counter":
                out.append(point)
            elif point.cumulative:
                rate = self._cumulative_rate(point)
                if rate is not None:
                    out.append(replace(point, value=rate))
            else:
                seconds = (point.timestamp - point.start_time).total_seconds() if point.start_time else 0
                # Without a start time the interval is unknown; the count per send still tracks the rate.
                out.append(replace(point, value=point.value / seconds) if seconds > 0 else point)
        return out

    def _cumulative_rate(self, point: OtlpPoint) -> float | None:
        key = (point.metric_name, point.service, frozenset(point.attributes.items()))
        with self._lock:
            previous = self._last.get(key)
            if previous is not None and point.timestamp <= previous[0]:
                return None
            self._last[key] = (point.timestamp, point.value, point.start_time)
        if previous is None:
            return None
        previous_time, previous_value, previous_start = previous
        increase = point.value - previous_value
        restarted = increase < 0 or (point.start_time is not None and previous_start is not None and point.start_time != previous_start)
        if restarted:
            # The counter started again from zero, so everything it holds is new (as rate() counts a reset).
            increase = point.value
        return increase / (point.timestamp - previous_time).total_seconds()


counter_rates = CounterRates()
