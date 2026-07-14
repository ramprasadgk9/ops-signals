from __future__ import annotations

from datetime import timedelta
from datetime import datetime
from typing import Any


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


def evaluate_correlation(definition: dict[str, Any], matched_inputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    correlation = definition.get("correlation", {}) or {}
    input_windows = [
        (
            _parse_datetime(item.get("signal", {}).get("window_start")),
            _parse_datetime(item.get("signal", {}).get("window_end")),
        )
        for item in matched_inputs.values()
        if item.get("signal", {}).get("window_start") and item.get("signal", {}).get("window_end")
    ]
    if not input_windows:
        return {"matched": False, "reason": "no overlapping signal windows"}
    starts = [start for start, _ in input_windows]
    ends = [end for _, end in input_windows]
    overlap = min(ends) >= max(starts)
    minimum_overlap = parse_duration(correlation.get("minimum_overlap"), 0)
    max_gap = parse_duration(correlation.get("max_time_gap"), 0)
    return {
        "matched": bool(overlap),
        "same_analysis_context": bool(correlation.get("same_analysis_context", True)),
        "minimum_overlap": minimum_overlap.total_seconds() / 60,
        "max_time_gap": max_gap.total_seconds() / 60,
        "overlap": overlap,
    }
