from __future__ import annotations

from datetime import timedelta
from datetime import datetime
from itertools import product
from typing import Any

# Fact groups that carry the times their signals were active (fact_extractor's "windows").
TIMED_FACT_GROUPS = ("anomaly", "trend", "baseline_shift", "ruptures", "change")
# Enough to cover realistic inputs (a few anomaly windows each); beyond it the remaining
# combinations are skipped rather than letting one evaluation run away.
MAX_WINDOW_COMBINATIONS = 10_000


def parse_duration(value: str | None, default_minutes: int = 0) -> timedelta:
    if not value:
        return timedelta(minutes=default_minutes)
    value = value.strip().lower()
    if value.endswith("m"):
        return timedelta(minutes=int(value[:-1]))
    if value.endswith("h"):
        return timedelta(hours=int(value[:-1]))
    return timedelta(minutes=default_minutes)


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _groups_by_alias(condition_matches: list[dict[str, Any]] | None) -> dict[str, set[str]]:
    """The fact groups whose conditions passed, per input alias - e.g. {"latency": {"anomaly"}} for
    a passing "latency.anomaly.present". Those signals are what the behavior is actually about."""
    groups: dict[str, set[str]] = {}
    for match in condition_matches or []:
        if not match.get("passed"):
            continue
        parts = str(match.get("fact", "")).split(".")
        if len(parts) >= 2 and parts[1] in TIMED_FACT_GROUPS:
            groups.setdefault(parts[0], set()).add(parts[1])
    return groups


def _input_windows(item: dict[str, Any], groups: set[str] | None) -> list[tuple[datetime, datetime]]:
    """When this input's relevant signals were active: the windows of the fact groups its passing
    conditions name, or of all its signals when they name none (e.g. only signal.count)."""
    if groups:
        raw = [window for group in sorted(groups) for window in (item.get(group, {}) or {}).get("windows", [])]
    else:
        raw = (item.get("signal", {}) or {}).get("windows")
        if raw is None:
            # Facts stored before per-signal windows existed: fall back to the overall window.
            signal = item.get("signal", {}) or {}
            raw = [[signal.get("window_start"), signal.get("window_end")]]
    windows = []
    for start_value, end_value in raw:
        start, end = _parse_datetime(start_value), _parse_datetime(end_value)
        if start and end:
            windows.append((start, end))
    return windows


def evaluate_correlation(
    definition: dict[str, Any],
    matched_inputs: dict[str, dict[str, Any]],
    condition_matches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Whether the inputs' signals happened close enough in time to count as one behavior.

    Inputs are related when some choice of one signal window per input either overlaps by at least
    `minimum_overlap` or sits within `max_time_gap` of each other (overlapping counts as a gap of 0).
    With neither set, the windows must overlap. A single-point anomaly has no duration, so it can
    only satisfy `max_time_gap`; that is why definitions set both."""
    correlation = definition.get("correlation", {}) or {}
    minimum_overlap = parse_duration(correlation.get("minimum_overlap"), 0)
    max_gap = parse_duration(correlation.get("max_time_gap"), 0)
    result = {
        "same_analysis_context": bool(correlation.get("same_analysis_context", True)),
        "minimum_overlap": minimum_overlap.total_seconds() / 60,
        "max_time_gap": max_gap.total_seconds() / 60,
    }

    groups = _groups_by_alias(condition_matches)
    per_input = [_input_windows(item, groups.get(alias)) for alias, item in matched_inputs.items()]
    if not per_input or any(not windows for windows in per_input):
        return {**result, "matched": False, "overlap": False, "reason": "no signal windows to correlate"}

    best_overlap: timedelta | None = None
    for count, combination in enumerate(product(*per_input)):
        if count >= MAX_WINDOW_COMBINATIONS:
            break
        # Positive: how long every window in this combination overlaps; negative: the gap between them.
        overlap = min(end for _, end in combination) - max(start for start, _ in combination)
        if best_overlap is None or overlap > best_overlap:
            best_overlap = overlap

    overlap_minutes = best_overlap.total_seconds() / 60
    if max_gap or minimum_overlap:
        matched = (bool(max_gap) and best_overlap >= -max_gap) or (bool(minimum_overlap) and best_overlap >= minimum_overlap)
    else:
        matched = best_overlap >= timedelta(0)
    return {
        **result,
        "matched": bool(matched),
        "overlap": best_overlap >= timedelta(0),
        "closest_gap_minutes": round(max(0.0, -overlap_minutes), 1),
        "overlap_minutes": round(max(0.0, overlap_minutes), 1),
    }
