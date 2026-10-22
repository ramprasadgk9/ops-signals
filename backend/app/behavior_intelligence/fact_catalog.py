from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FactDescriptor:
    key: str
    description: str
    example: object


# Every fact a behavior definition condition can reference, under an input alias
# (e.g. "cpu.anomaly.present" = alias "cpu" + fact key "anomaly.present"). Produced by
# fact_extractor.extract_facts() per metric. Kept as the single source of truth for both the
# `/api/behavior-definitions/facts` endpoint and definition validation, so the two can't drift.
FACT_DESCRIPTORS: list[FactDescriptor] = [
    FactDescriptor("anomaly.present", "Whether any anomaly signal was found for this metric in the window.", True),
    FactDescriptor("anomaly.count", "How many anomaly signals were found.", 2),
    FactDescriptor("anomaly.max_score", "The highest importance score among the anomaly signals (0-1).", 0.82),
    FactDescriptor("anomaly.windows", "When each anomaly signal was active, as [start, end] pairs.", [["2026-09-10T01:10:00+00:00", "2026-09-10T01:25:00+00:00"]]),
    FactDescriptor("trend.present", "Whether a trend signal was found for this metric in the window.", True),
    FactDescriptor("trend.direction", "Which way the metric is moving overall.", "upward"),
    FactDescriptor("trend.change_percent", "Magnitude of the trend change, as an absolute percentage.", 34.5),
    FactDescriptor("trend.slope", "Raw trend slope value from the analyzer's regression.", 0.12),
    FactDescriptor("trend.windows", "When each trend signal was active, as [start, end] pairs.", [["2026-09-10T00:00:00+00:00", "2026-09-10T02:00:00+00:00"]]),
    FactDescriptor("baseline_shift.present", "Whether a baseline/regime shift was detected for this metric.", False),
    FactDescriptor("baseline_shift.change_percent", "Size of the detected baseline shift, as an absolute percentage.", 40.0),
    FactDescriptor("baseline_shift.signed_change_percent", "The detected baseline shift as a signed percentage: positive means the metric moved up.", 40.0),
    FactDescriptor("baseline_shift.windows", "From each baseline shift's change point to the end of the window, as [start, end] pairs.", [["2026-09-10T01:00:00+00:00", "2026-09-10T02:00:00+00:00"]]),
    FactDescriptor("ruptures.present", "Whether a ruptures change-point signal was found for this metric.", False),
    FactDescriptor("ruptures.change_percent", "Size of the detected change point, as an absolute percentage.", 25.0),
    FactDescriptor("ruptures.signed_change_percent", "The detected change point as a signed percentage: positive means the metric moved up.", 25.0),
    FactDescriptor("ruptures.change_point_index", "Sample index where the change point was detected.", 80),
    FactDescriptor("ruptures.windows", "From each change point to the end of the window, as [start, end] pairs.", [["2026-09-10T01:20:00+00:00", "2026-09-10T02:00:00+00:00"]]),
    FactDescriptor("change.present", "Whether the metric went up or down, by any of trend, baseline_shift or ruptures (a ruptures change of more than 25%).", True),
    FactDescriptor("change.upward", "Whether any of those saw the metric go up. Use this for \"went up\", whichever analyzer ran.", True),
    FactDescriptor("change.downward", "Whether any of those saw the metric go down.", False),
    FactDescriptor("change.direction", "upward, downward, mixed (both were seen) or none.", "upward"),
    FactDescriptor("change.change_percent", "Size of the largest of those changes, as an absolute percentage.", 49.0),
    FactDescriptor("change.signed_change_percent", "The largest of those changes as a signed percentage: positive means the metric went up.", 49.0),
    FactDescriptor("change.sources", "Which analyzers saw the change: trend, baseline_shift, ruptures.", ["ruptures"]),
    FactDescriptor("change.windows", "When each of those changes was active, as [start, end] pairs.", [["2026-09-10T01:20:00+00:00", "2026-09-10T02:00:00+00:00"]]),
    FactDescriptor("signal.count", "Total number of signals of any type found for this metric.", 3),
    FactDescriptor("signal.types", "Distinct signal_type values present for this metric.", ["anomaly_zscore", "trend"]),
    FactDescriptor("signal.window_start", "Earliest signal start_time for this metric in the window.", "2026-09-10T00:00:00+00:00"),
    FactDescriptor("signal.window_end", "Latest signal end_time for this metric in the window.", "2026-09-10T02:00:00+00:00"),
    FactDescriptor("signal.windows", "When each signal of any type was active, as [start, end] pairs.", [["2026-09-10T01:10:00+00:00", "2026-09-10T01:25:00+00:00"]]),
]

FACT_KEYS: set[str] = {descriptor.key for descriptor in FACT_DESCRIPTORS}


def fact_root(fact_path: str) -> str | None:
    """Given a full condition fact path like "cpu.anomaly.present", return the fact key
    ("anomaly.present") with the alias stripped — the part that must exist in FACT_KEYS."""
    parts = fact_path.split(".", 1)
    return parts[1] if len(parts) == 2 else None
