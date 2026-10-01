"""Break a service-level finding down by pod (or another label) to show where the change came from.

A finding says "checkout errors rose 308% at 14:08"; the breakdown adds "91% of that came from pod
checkout-x2" or "all 6 pods rose by a similar amount". Those call for different responses (fix one
instance vs look at code, config or a shared dependency), yet look identical at service level.

Everything here is pure - no Prometheus, no database - so the arithmetic is unit-tested on its own:
  - breakdown_window: the before/after split, taken from the finding's own signals;
  - rewrite_for_breakdown: the service-level PromQL re-grouped by one more label;
  - compute_breakdown: each part's change and how concentrated it is.

Two modes, because shares only add up for additive metrics:
  - "share" (sum/count of rates, counts): each part's change / the total change; shares sum to 1.
  - "changed_parts" (averages, maxima, percentiles, ratios): per-pod values don't add up to the
    service value, so a percentage share would be meaningless. Instead: which parts moved, and how.

The spread (concentrated / partial / widespread) is decided the same way in both modes: by how far
each part moved from its *own* normal level, not by its share. Pods carry different traffic, so when
every pod's errors double, the busiest pod still holds the biggest share of the increase - a share
rule would call that "concentrated" and send the engineer to restart one healthy pod.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import pandas as pd

from intelligence.signals.schema import OperationalSignal

# A part counts as moved if its change, relative to its own normal level, is at least this
# fraction of the largest relative change, in the same direction.
MOVED_FRACTION_OF_MAX = 0.5
# Share mode: a part with almost no normal traffic that also holds almost none of the change is left
# out of "moved" - a pod going from 0.001 to 0.01 errors/s is a 10x change nobody would notice. Both
# conditions are needed: a quiet pod that suddenly holds the change is exactly the one to report,
# and a normal-sized pod is never ignored however small its slice.
MIN_MATERIAL_SHARE = 0.05
MIN_MATERIAL_LEVEL = 0.05  # of the typical part's normal level
# Parts listed individually; the rest are summed into "others".
TOP_PARTS = 5
MIN_BASELINE_POINTS = 3

_LOCALIZED_SIGNAL_TYPES = {"anomaly", "spike", "outlier"}
_AGGREGATIONS = {"sum", "count", "avg", "max", "min"}
_ADDITIVE_AGGREGATIONS = {"sum", "count"}
_LABEL_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


@dataclass(frozen=True, slots=True)
class BreakdownWindow:
    before_start: datetime
    change_start: datetime
    change_end: datetime


@dataclass(frozen=True, slots=True)
class BreakdownQuery:
    query: str
    mode: str  # "share" | "changed_parts"


def breakdown_window(
    signals: Iterable[OperationalSignal],
    series_start: datetime,
    series_end: datetime,
) -> BreakdownWindow | None:
    """The stretch to explain ("after") and the stretch to compare it with ("before").

    A change point (ruptures, baseline_shift) splits the series in two: before = everything up to
    the break, after = everything from it. A short unusual stretch (an anomaly or outlier group) is
    compared with the stretch just before it: as long as the anomaly itself, or a quarter of the
    history before it if that is longer, so a few noisy points don't set the baseline. A signal
    covering the whole series with no
    change point (a trend, a forecast) has no moment to split at, so it gives no window.
    """
    # Analyzers gated by a finding rule emit a signal even when the rule didn't match (for
    # diagnostics); only signals that are actual detections may place the window.
    signals = [signal for signal in signals if (signal.evidence or {}).get("finding_rule_matched", True)]
    change_points = sorted(
        point for point in (_change_point_time(signal) for signal in signals) if point is not None
    )
    if change_points:
        change_start = change_points[0]
        if change_start <= series_start or change_start >= series_end:
            return None
        return BreakdownWindow(before_start=series_start, change_start=change_start, change_end=series_end)

    localized = [
        signal
        for signal in signals
        if signal.signal_type in _LOCALIZED_SIGNAL_TYPES
        and not (_utc(signal.start_time) <= series_start and _utc(signal.end_time) >= series_end)
    ]
    if not localized:
        return None
    change_start = min(_utc(signal.start_time) for signal in localized)
    change_end = max(_utc(signal.end_time) for signal in localized)
    if change_start <= series_start:
        return None
    length = max(change_end - change_start, (change_start - series_start) / 4)
    before_start = max(series_start, change_start - length)
    return BreakdownWindow(before_start=before_start, change_start=change_start, change_end=change_end)


def rewrite_for_breakdown(promql: str, label: str) -> BreakdownQuery | None:
    """The same query grouped by one more label, or None when the query shape isn't supported.

    Handles the shapes the autonomous planner builds - `AGG by (labels) (inner)` and
    `histogram_quantile(q, sum by (le, labels) (inner))` - and nothing else. An unrecognised query
    is reported as unsupported instead of guessed at: a wrong rewrite would explain the finding
    with the wrong data.
    """
    if not _LABEL_NAME.match(label):
        return None
    text = promql.strip()

    histogram = re.match(r"^histogram_quantile\(\s*([0-9.]+)\s*,\s*(.*)\)$", text, flags=re.DOTALL)
    if histogram:
        inner = _rewrite_aggregation(histogram.group(2).strip(), label)
        if inner is None or not inner[1].startswith("sum"):
            return None
        return BreakdownQuery(query=f"histogram_quantile({histogram.group(1)}, {inner[0]})", mode="changed_parts")

    rewritten = _rewrite_aggregation(text, label)
    if rewritten is None:
        return None
    query, aggregation = rewritten
    mode = "share" if aggregation in _ADDITIVE_AGGREGATIONS else "changed_parts"
    return BreakdownQuery(query=query, mode=mode)


def compute_breakdown(
    parts: pd.DataFrame,
    *,
    label: str,
    window: BreakdownWindow,
    mode: str,
) -> dict[str, object]:
    """Each part's change between the two windows, and how concentrated the change is.

    parts: one row per sample, columns `part` (the label value, e.g. a pod name), `timestamp`, `value`.
    Returns the `breakdown` dict stored on the finding; `status` is "ok" or "skipped" with a reason.
    """
    base: dict[str, object] = {
        "label": label,
        "mode": mode,
        "window_before": [window.before_start.isoformat(), window.change_start.isoformat()],
        "window_after": [window.change_start.isoformat(), window.change_end.isoformat()],
    }
    if parts.empty:
        return {**base, "status": "skipped", "reason": "no_data"}

    frame = parts.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["value"])
    frame = frame[frame["value"].map(math.isfinite)]
    before = frame[(frame["timestamp"] >= window.before_start) & (frame["timestamp"] < window.change_start)]
    after = frame[(frame["timestamp"] >= window.change_start) & (frame["timestamp"] <= window.change_end)]
    # A part with fewer than MIN_BASELINE_POINTS samples before the change has no normal level to
    # compare with: it started just before the change point (which often lands a scrape or two
    # after a rollout's new pods come up), so it counts as new rather than as a pod that "moved".
    before_counts = before.groupby("part")["value"].size()
    before = before[before["part"].isin(before_counts[before_counts >= MIN_BASELINE_POINTS].index)]

    names = sorted(set(before["part"]) | set(after["part"]))
    if len(names) < 2:
        return {**base, "status": "skipped", "reason": "single_part", "parts_total": len(names)}
    if len(before) < MIN_BASELINE_POINTS:
        return {**base, "status": "skipped", "reason": "not_enough_baseline", "parts_total": len(names)}

    before_means = before.groupby("part")["value"].mean()
    after_means = after.groupby("part")["value"].mean()
    # A part with no "before" data is new (e.g. a pod started by a rollout). Additive: it
    # contributed nothing before. Either way, whether it *moved* is judged against what the other
    # parts normally do.
    typical_before = float(before_means.abs().median())
    new_part_baseline = 0.0 if mode == "share" else float(before_means.median())
    # Relative changes divide by the part's normal level; a part normally at zero gets this floor
    # instead, so going from 0 to something registers as a large change, not an infinite one.
    level_floor = max(0.1 * typical_before, 1e-9)

    rows = []
    for name in names:
        is_new = name not in before_means.index
        is_gone = name not in after_means.index
        before_value = new_part_baseline if is_new else float(before_means[name])
        after_value = 0.0 if (is_gone and mode == "share") else (None if is_gone else float(after_means[name]))
        change = None if after_value is None else after_value - before_value
        reference = float(before_means.median()) if is_new else before_value
        relative = None if after_value is None else (after_value - reference) / max(abs(reference), level_floor)
        rows.append(
            {
                "value": str(name),
                "before": round(before_value, 6) if not is_new else None,
                "after": round(after_value, 6) if after_value is not None else None,
                "change": round(change, 6) if change is not None else None,
                "relative_change": round(relative, 4) if relative is not None else None,
                "new": is_new,
                "gone": is_gone,
                "_change": change,
                "_relative": relative,
                "_negligible_level": not is_new and abs(before_value) < MIN_MATERIAL_LEVEL * typical_before,
            }
        )

    if mode == "share":
        total = sum(row["_change"] for row in rows if row["_change"] is not None)
        scale = max((abs(row["_change"]) for row in rows if row["_change"] is not None), default=0.0)
        if scale == 0.0 or abs(total) <= 1e-9 * max(scale, 1.0):
            return {**base, "status": "skipped", "reason": "no_net_change", "parts_total": len(names)}
        for row in rows:
            row["share"] = round(row["_change"] / total, 4) if row["_change"] is not None else 0.0

    direction = _mark_moved(rows, mode)
    if direction is None:
        return {**base, "status": "skipped", "reason": "no_net_change", "parts_total": len(names)}
    moved = sum(1 for row in rows if row["moved"])
    if moved == 1:
        spread = "concentrated"
    elif moved / len(rows) > 0.5:
        spread = "widespread"
    else:
        spread = "partial"

    if mode == "share":
        ordered = sorted(rows, key=lambda row: row["share"], reverse=True)
    else:
        ordered = sorted(rows, key=lambda row: (row["_relative"] is None, -(row["_relative"] or 0.0) * direction))
    others = ordered[TOP_PARTS:]
    summary_of_others: dict[str, object] | None = None
    if others:
        summary_of_others = {"count": len(others), "moved": sum(1 for row in others if row["moved"])}
        if mode == "share":
            summary_of_others["share"] = round(sum(row["share"] for row in others), 4)

    return {
        **base,
        "status": "ok",
        "parts_total": len(names),
        "parts_changed": moved,
        "spread": spread,
        "direction": "up" if direction > 0 else "down",
        "new_parts": sum(1 for row in rows if row["new"]),
        "gone_parts": sum(1 for row in rows if row["gone"]),
        **({"total_change": round(total, 6)} if mode == "share" else {}),
        "top": [_public(row) for row in ordered[:TOP_PARTS]],
        "others": summary_of_others,
    }


def _mark_moved(rows: list[dict[str, object]], mode: str) -> float | None:
    """Set row["moved"]; return the direction of the change (+1 up, -1 down), or None if nothing moved."""
    eligible = [
        row
        for row in rows
        if row["_relative"] is not None
        and not (mode == "share" and row["_negligible_level"] and abs(row["share"]) < MIN_MATERIAL_SHARE)
    ]
    for row in rows:
        row["moved"] = False
    if not eligible:
        return None
    largest = max(eligible, key=lambda row: abs(row["_relative"]))
    if largest["_relative"] == 0.0:
        return None
    direction = math.copysign(1.0, largest["_relative"])
    threshold = abs(largest["_relative"]) * MOVED_FRACTION_OF_MAX
    for row in eligible:
        row["moved"] = row["_relative"] * direction >= threshold
    return direction


def _public(row: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in row.items() if not key.startswith("_")}


def _rewrite_aggregation(text: str, label: str) -> tuple[str, str] | None:
    match = re.match(r"^(\w+)\s+by\s*\(([^()]*)\)\s*\(", text)
    if not match or match.group(1) not in _AGGREGATIONS:
        return None
    body_start = match.end() - 1
    if _matching_paren(text, body_start) != len(text) - 1:
        return None
    labels = [item.strip() for item in match.group(2).split(",") if item.strip()]
    if label in labels:
        return None
    grouped = ", ".join([*labels, label])
    return f"{match.group(1)} by ({grouped}) {text[body_start:]}", match.group(1)


def _matching_paren(text: str, open_index: int) -> int | None:
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(open_index, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in "\"'`":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def _change_point_time(signal: OperationalSignal) -> datetime | None:
    raw = (signal.evidence or {}).get("change_point_time")
    if not raw:
        return None
    try:
        return _utc(pd.Timestamp(raw).to_pydatetime())
    except (TypeError, ValueError):
        return None


def _utc(value: datetime) -> datetime:
    timestamp = pd.Timestamp(value)
    timestamp = timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")
    return timestamp.to_pydatetime()
