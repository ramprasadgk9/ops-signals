"""Finding events from a causal replay, each labeled against an answer key, and rate tables.

A replay analyzes a trailing window every `step` rows, the way a scheduled production run would
(the same cadence as benchmark/nab/detector.py). A finding event is what a user would newly see at
one run: the new user-facing signals of one finding. A signal is dated by the moment it points at
(signal_row: a change point or pattern position from its evidence, else its start). Signals older
than the new-event horizon, or that repeat an alarm already raised (same analyzer and signal type,
within one step - or the horizon, for a pinpointed change - confidence no higher), are not new.
Signals about the whole window (a trend fit) point at no moment, are always old, and never count.

Each event records the group a trust number would be looked up by:

- type: the finding category of its new signals, with the product's own precedence
  (FindingAggregator._category) - so an old level change in the window doesn't relabel a new spike
- agreement: whether 2+ different analyzers raised it
- importance band: the finding's importance score, cut where the product cuts health status

Labeling works on plain numbers (row indexes or epoch seconds), so the same code labels NAB rows
and RCAEval timestamps.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

import numpy as np
import pandas as pd

from benchmark import harness
from intelligence.finding_aggregator import FindingAggregator

# Outcomes. Only in_incident counts as "real"; before_incident is reported apart, as early warning.
IN_INCIDENT = "in_incident"
BEFORE_INCIDENT = "before_incident"
FALSE_ALARM = "false_alarm"
NOT_SCORED = "not_scored"

# The smallest group a trust number is shown from; smaller groups fall back to a broader one.
MIN_GROUP = 30

TYPE_LABELS = {
    "data_quality": "Data problem (gap or frozen value)",
    "behavior_change": "New level or steady trend",
    "unusual_activity": "Short spike or dip",
    "operational_insight": "Pattern or forecast",
}


@dataclass(slots=True)
class FindingEvent:
    # The run's last row: the first moment a user could have seen this finding.
    row: int
    finding_type: str
    analyzers: tuple[str, ...]
    importance: float
    confidence: float
    # Filled in by labeling.
    outcome: str = NOT_SCORED
    # Marked anomaly moment minus the event's moment, in the caller's units; > 0 means it came first.
    lead: float | None = None
    source: dict[str, Any] = field(default_factory=dict)

    @property
    def agreement(self) -> str:
        return "2+ analyzers" if len(self.analyzers) >= 2 else "1 analyzer"

    @property
    def band(self) -> str:
        return importance_band(self.importance)

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["analyzers"] = list(self.analyzers)
        record.update(agreement=self.agreement, band=self.band)
        return record


def importance_band(importance: float) -> str:
    # The same cuts as FindingAggregator._health_status: critical / significant / normal.
    if importance >= 0.8:
        return "high"
    if importance >= 0.55:
        return "medium"
    return "low"


def replay_events(
    pipeline,
    frame: pd.DataFrame,
    *,
    step: int,
    window: int,
    horizon: int,
    min_history: int,
) -> tuple[list[FindingEvent], int, int]:
    """Replay `frame` (timestamp, value, metric_name) and return (events, runs, errors)."""
    times = frame["timestamp"].dt.tz_convert(None).to_numpy()
    columns = frame[["timestamp", "value", "metric_name"]]
    aggregator = FindingAggregator()
    raised: dict[tuple[str, str], list[tuple[int, float]]] = {}
    events: list[FindingEvent] = []
    runs = errors = 0
    for end in range(min(min_history, len(frame) - 1), len(frame), step):
        runs += 1
        try:
            result = pipeline.run_dataframe(columns.iloc[max(0, end - window + 1) : end + 1])
        except Exception:
            errors += 1
            continue
        by_id = {signal.signal_id: signal for signal in harness.user_facing_signals(result)}
        for finding in result.findings:
            new = []
            for signal_id in finding.signal_ids:
                signal = by_id.get(signal_id)
                if signal is None:
                    continue
                start_row, pinpointed = signal_row(signal, times, max(0, end - window + 1))
                if start_row is None or start_row < end - horizon:
                    continue
                key = (str(signal.analyzer_id), str(signal.signal_type))
                confidence = float(signal.confidence)
                # A change point's estimated row moves a little as data arrives; still the same change.
                tolerance = horizon if pinpointed else step
                if any(abs(start_row - row) <= tolerance and earlier >= confidence for row, earlier in raised.get(key, [])):
                    continue
                raised.setdefault(key, []).append((start_row, confidence))
                new.append(signal)
            if new:
                events.append(
                    FindingEvent(
                        row=end,
                        finding_type=aggregator._category(new),
                        analyzers=tuple(sorted({str(signal.analyzer_id) for signal in new})),
                        importance=round(float(finding.importance_score), 4),
                        confidence=round(max(float(signal.confidence) for signal in new), 4),
                    )
                )
    return events, runs, errors


def signal_row(signal, times: np.ndarray, window_first: int) -> tuple[int | None, bool]:
    """The row a signal is about, and whether the analyzer pinpointed it. Change-point and pattern
    analyzers (ruptures, baseline_shift, stumpy) start their signal at the window's first row and
    put the moment they found in the evidence; without this, every one of them looks weeks old."""
    evidence = getattr(signal, "evidence", None) or {}
    if evidence.get("change_point_time"):
        return row_at_or_after(times, evidence["change_point_time"]), True
    for key in ("discord_index", "motif_index"):
        if evidence.get(key) is not None:
            row = window_first + int(evidence[key])
            return (row if row < len(times) else None), True
    return row_at_or_after(times, signal.start_time), False


def row_at_or_after(times: np.ndarray, moment) -> int | None:
    stamp = pd.Timestamp(moment)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("UTC").tz_localize(None)
    row = int(np.searchsorted(times, stamp.to_datetime64(), side="left"))
    return row if row < len(times) else None


def label(
    at: float,
    windows: list[tuple[float, float]],
    anomalies: Iterable[float] = (),
    *,
    scored_from: float = float("-inf"),
    scored_until: float = float("inf"),
    before: float | None = None,
) -> tuple[str, float | None]:
    """(outcome, lead) for an event at `at`.

    in_incident: inside a marked window. before_incident: not inside one, but at most `before`
    units ahead of a window's start (default: that window's own length). false_alarm: neither.
    not_scored: outside [scored_from, scored_until] (NAB's probationary period, RCAEval's tail).
    The lead is measured to the marked anomaly moment of that window, when one is given.
    """
    if at < scored_from or at > scored_until:
        return NOT_SCORED, None
    marks = sorted(anomalies)
    for start, end in windows:
        if start <= at <= end:
            return IN_INCIDENT, _lead(at, marks, start, end)
    for start, end in sorted(windows):
        reach = before if before is not None else (end - start)
        if start - reach <= at < start:
            return BEFORE_INCIDENT, _lead(at, marks, start, end)
    return FALSE_ALARM, None


def _lead(at: float, marks: list[float], start: float, end: float) -> float | None:
    inside = [mark for mark in marks if start <= mark <= end]
    return (inside[0] - at) if inside else None


# Group levels, most specific first: the fallback order a finding's trust number is looked up in.
LEVELS = (
    ("type, agreement, importance", ("finding_type", "agreement", "band")),
    ("type, agreement", ("finding_type", "agreement")),
    ("type", ("finding_type",)),
)


def rate_tables(events: list[FindingEvent]) -> dict[str, list[dict[str, Any]]]:
    """Per group level, one row per group: how many scored events, and how they turned out."""
    scored = [event for event in events if event.outcome != NOT_SCORED]
    tables: dict[str, list[dict[str, Any]]] = {}
    for name, keys in LEVELS:
        groups: dict[tuple, list[FindingEvent]] = {}
        for event in scored:
            groups.setdefault(tuple(_attr(event, key) for key in keys), []).append(event)
        tables[name] = sorted(
            (_row(dict(zip(keys, key)), members) for key, members in groups.items()),
            key=lambda row: (-row["n"], str(row["group"])),
        )
    combos: dict[tuple, list[FindingEvent]] = {}
    for event in scored:
        combos.setdefault((event.finding_type, event.analyzers), []).append(event)
    tables["type, exact analyzers"] = sorted(
        (_row({"finding_type": key[0], "analyzers": "+".join(key[1])}, members) for key, members in combos.items()),
        key=lambda row: (-row["n"], str(row["group"])),
    )
    return tables


def overall(events: list[FindingEvent]) -> dict[str, Any]:
    return _row({}, [event for event in events if event.outcome != NOT_SCORED])


def lookup(event: FindingEvent, tables: dict[str, list[dict[str, Any]]], min_n: int = MIN_GROUP) -> dict[str, Any] | None:
    """The trust number a user would see for `event`: the most specific group with >= min_n
    checked, with the level it came from. None when even the type has fewer."""
    for name, keys in LEVELS:
        wanted = {key: _attr(event, key) for key in keys}
        for row in tables.get(name, []):
            if row["group"] == wanted and row["n"] >= min_n:
                return {**row, "level": name}
    return None


def _attr(event: FindingEvent, key: str) -> str:
    return str(getattr(event, key))


def _row(group: dict[str, str], members: list[FindingEvent]) -> dict[str, Any]:
    n = len(members)
    counts = {outcome: sum(1 for event in members if event.outcome == outcome) for outcome in (IN_INCIDENT, BEFORE_INCIDENT, FALSE_ALARM)}
    leads = [event.lead for event in members if event.lead is not None and event.outcome in (IN_INCIDENT, BEFORE_INCIDENT)]
    chances = [event.source["chance"] for event in members if event.source.get("chance") is not None]
    chance = sum(chances) / len(chances) if chances else None
    real_rate = counts[IN_INCIDENT] / n if n else None
    return {
        "group": group,
        "n": n,
        "real": counts[IN_INCIDENT],
        "early": counts[BEFORE_INCIDENT],
        "false": counts[FALSE_ALARM],
        "real_rate": counts[IN_INCIDENT] / n if n else None,
        "early_rate": counts[BEFORE_INCIDENT] / n if n else None,
        "false_rate": counts[FALSE_ALARM] / n if n else None,
        "real_rate_low": wilson_low(counts[IN_INCIDENT], n),
        # What an alarm at a random moment would score on the same data: the share of scored time
        # inside incidents. A group is only informative if its real rate is well above this.
        "chance": chance,
        "lift": real_rate / chance if real_rate is not None and chance else None,
        "median_lead": statistics.median(leads) if leads else None,
        "warned_first": sum(1 for lead in leads if lead > 0),
        "with_lead": len(leads),
    }


def chance_rate(windows: list[tuple[float, float]], scored_from: float, scored_until: float) -> float | None:
    """Share of [scored_from, scored_until] inside the windows: how often a random alarm is "real"."""
    span = scored_until - scored_from
    if span <= 0:
        return None
    inside = sum(max(0.0, min(end, scored_until) - max(start, scored_from)) for start, end in windows)
    return min(1.0, inside / span)


def wilson_low(successes: int, n: int, z: float = 1.96) -> float | None:
    """Lower end of the 95% Wilson interval: the rate we can still claim given only n checked."""
    if not n:
        return None
    p = successes / n
    centre = p + z * z / (2 * n)
    spread = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return max(0.0, (centre - spread) / (1 + z * z / n))
