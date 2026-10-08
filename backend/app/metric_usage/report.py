"""Join every metric Prometheus has with what reads it and what Ops Signals found, into one group
per metric:

- blind_spot: nothing watches it (no dashboard, no alert) and it had a recent problem finding.
- missing: a dashboard or alert reads it, but Prometheus has no such metric - an empty panel.
- watched: a dashboard or alert reads it, directly or through recording rules.
- unwatched: nothing reads it and nothing is wrong with it.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from backend.app.metric_usage.sources import MetricUsage, UsageScan

WATCHING_KINDS = {"dashboard", "alert_rule"}
# Stored but read by no dashboard or alert: what unused-storage cost is counted from.
UNUSED_STATUSES = {"blind_spot", "unwatched"}
_STATUS_ORDER = {"blind_spot": 0, "missing": 1, "watched": 2, "unwatched": 3}


@dataclass(frozen=True)
class MetricReportItem:
    metric: str
    status: str
    connections: tuple[str, ...] = ()
    usages: tuple[MetricUsage, ...] = ()
    # Recording rules whose (watched) output this metric feeds.
    via_recording_rules: tuple[str, ...] = ()
    problem_findings: int = 0
    latest_finding_id: int | None = None
    analyzed: bool = False
    # Active series, summed over connections; None when no connection reported series counts.
    series: int | None = None


@dataclass(frozen=True)
class MetricUsageReport:
    items: list[MetricReportItem]
    totals: dict[str, int | None]


def build_report(
    metrics_by_connection: Mapping[str, Iterable[str]],
    scan: UsageScan,
    problems: Mapping[str, tuple[int, int]] | None = None,
    analyzed: Iterable[str] = (),
    ignore_metrics: Iterable[str] = (),
    series_by_connection: Mapping[str, Mapping[str, int]] | None = None,
) -> MetricUsageReport:
    """`problems` maps a metric to (problem finding count, latest finding id); `series_by_connection`
    maps a connection to its active series per metric, where the backend could count them."""
    problems = problems or {}
    analyzed = set(analyzed)
    ignore = [pattern for pattern in ignore_metrics if pattern]

    def ignored(name: str) -> bool:
        return any(fnmatch.fnmatchcase(name, pattern) for pattern in ignore)

    connections: dict[str, list[str]] = {}
    for connection_id, names in metrics_by_connection.items():
        for name in names:
            if not ignored(name):
                connections.setdefault(name, []).append(connection_id)

    usages: dict[str, list[MetricUsage]] = {}
    for usage in scan.usages:
        usages.setdefault(usage.metric, []).append(usage)

    watched = {metric for metric, found in usages.items() if any(usage.kind in WATCHING_KINDS for usage in found)}
    via: dict[str, list[str]] = {}
    changed = True
    while changed:  # a watched recording rule makes the metrics it reads watched, through chains
        changed = False
        for rule_name, sources in scan.recording_rules.items():
            if rule_name not in watched:
                continue
            for source in sources:
                if rule_name not in via.setdefault(source, []):
                    via[source].append(rule_name)
                if source not in watched:
                    watched.add(source)
                    changed = True

    series_by_connection = series_by_connection or {}

    def series_of(metric: str) -> int | None:
        counts = [series_by_connection[connection].get(metric, 0) for connection in connections.get(metric, []) if connection in series_by_connection]
        return sum(counts) if counts else None

    items: list[MetricReportItem] = []
    for metric in sorted(set(connections) | {name for name in watched if name in usages and not ignored(name)}):
        present = metric in connections
        count, latest = problems.get(metric, (0, None))
        if not present:
            if not any(usage.kind in WATCHING_KINDS for usage in usages.get(metric, [])):
                continue  # only read by a recording rule: not a panel anyone looks at
            status = "missing"
        elif metric in watched:
            status = "watched"
        elif count:
            status = "blind_spot"
        else:
            status = "unwatched"
        items.append(
            MetricReportItem(
                metric=metric,
                status=status,
                connections=tuple(connections.get(metric, [])),
                usages=tuple(usages.get(metric, [])),
                via_recording_rules=tuple(sorted(via.get(metric, []))),
                problem_findings=count,
                latest_finding_id=latest,
                analyzed=metric in analyzed,
                series=series_of(metric) if present else None,
            )
        )

    # Within a group: most problems first, then the most series (the biggest storage cost).
    items.sort(key=lambda item: (_STATUS_ORDER[item.status], -item.problem_findings, -(item.series or 0), item.metric))
    totals: dict[str, int | None] = {"metrics": len(connections), "watched": 0, "blind_spots": 0, "unwatched": 0, "missing": 0}
    for item in items:
        totals[{"blind_spot": "blind_spots"}.get(item.status, item.status)] += 1
    counted = [item for item in items if item.series is not None]
    totals["series_total"] = sum(item.series for item in counted) if counted else None
    totals["series_unwatched"] = sum(item.series for item in counted if item.status in UNUSED_STATUSES) if counted else None
    return MetricUsageReport(items, totals)
