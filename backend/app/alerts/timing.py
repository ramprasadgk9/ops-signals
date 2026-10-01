"""Pick the start time that change events are matched against, from the pattern the analyzers found.

Only signals with a real moment can set it: a step change's change point, or the start of a spike.
A trend spans the whole window, so it never sets a start time - it is reported as context instead,
and the message then makes no "started after" claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable

from backend.app.alerts.correlation import as_utc

# Analyzers whose evidence carries `change_point_time`, most specific first.
STEP_ANALYZERS = ("baseline_shift", "ruptures")
SPIKE_SIGNAL_TYPE = "anomaly"
TREND_SIGNAL_TYPE = "trend"

STEP_CHANGE = "step_change"
SPIKE = "spike"
TREND = "trend"
ALERT_TIME = "alert_time"


@dataclass
class StartTime:
    basis: str  # STEP_CHANGE | SPIKE | TREND | ALERT_TIME
    time: datetime | None = None  # set for STEP_CHANGE and SPIKE only
    analyzer_id: str | None = None
    trend_direction: str | None = None  # "upward" / "downward" when a trend was also found

    def to_dict(self) -> dict[str, Any]:
        return {
            "basis": self.basis,
            "time": self.time.isoformat() if self.time else None,
            "analyzer_id": self.analyzer_id,
            "trend_direction": self.trend_direction,
        }


def _parse(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return as_utc(value)
    if not value:
        return None
    try:
        return as_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def choose_start_time(
    signals: Iterable[Any],
    alert_starts_at: datetime,
    *,
    step_lookback: timedelta | None,
    spike_lookback: timedelta,
    after: timedelta,
) -> StartTime:
    """`signals` are pipeline OperationalSignals or stored SignalEntity rows: anything with
    `analyzer_id`, `signal_type`, `start_time` and `evidence` / `evidence_json`.

    A step change wins over a spike (a lasting jump is the strongest sign of a change event);
    among spikes, the latest one before the alert. Moments later than `after` past the alert, or
    older than the lookback, can't be what fired it and are ignored."""
    alert_at = as_utc(alert_starts_at)
    latest = alert_at + after
    steps: list[tuple[int, datetime, str]] = []
    spikes: list[tuple[datetime, str | None]] = []
    trend_direction = None
    for signal in signals:
        analyzer_id = getattr(signal, "analyzer_id", None)
        signal_type = getattr(signal, "signal_type", None)
        evidence = getattr(signal, "evidence", None) or getattr(signal, "evidence_json", None) or {}
        if analyzer_id in STEP_ANALYZERS:
            moment = _parse(evidence.get("change_point_time"))
            if moment and moment <= latest and (step_lookback is None or moment >= alert_at - step_lookback):
                steps.append((STEP_ANALYZERS.index(analyzer_id), moment, analyzer_id))
        elif signal_type == SPIKE_SIGNAL_TYPE:
            moment = _parse(getattr(signal, "start_time", None))
            if moment and alert_at - spike_lookback <= moment <= latest:
                spikes.append((moment, analyzer_id))
        elif signal_type == TREND_SIGNAL_TYPE and trend_direction is None:
            slope = evidence.get("slope")
            if isinstance(slope, (int, float)) and slope:
                trend_direction = "upward" if slope > 0 else "downward"

    if steps:
        # Most specific analyzer first, then the latest change point it reported.
        _, moment, analyzer_id = min(steps, key=lambda item: (item[0], -item[1].timestamp()))
        return StartTime(STEP_CHANGE, moment, analyzer_id, trend_direction)
    if spikes:
        moment, analyzer_id = max(spikes, key=lambda item: item[0])
        return StartTime(SPIKE, moment, analyzer_id, trend_direction)
    if trend_direction:
        return StartTime(TREND, trend_direction=trend_direction)
    return StartTime(ALERT_TIME)
