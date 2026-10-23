"""Join every metric Prometheus has with what reads it and what Ops Signals found, into one group
per metric:

- blind_spot: nothing watches it (no dashboard, no alert) and it had a recent problem finding.
- missing: a dashboard or alert reads it, but no connection its datasource reads has such a metric -
  an empty panel.
- watched: a dashboard or alert reads it, directly or through recording rules.
- unwatched: nothing reads it and nothing is wrong with it.

A usage counts only on the connections its datasource reads (MetricUsage.connections; None means any),
so a team-b panel doesn't watch team-a's metric of the same name.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from backend.app.metric_usage.sources import MetricUsage, UsageScan

WATCHING_KINDS = {"dashboard", "alert_rule"}
# Stored but read by no dashboard or alert: what unused-storage cost is counted from.
UNUSED_STATUSES = {"blind_spot", "unwatched"}
_STATUS_ORDER = {"blind_spot": 0, "missing": 1, "watched": 2, "unwatched": 3}
_FAMILY_SUFFIXES = ("_bucket", "_sum", "_count")
_FAMILY_TYPES = {"histogram", "gaugehistogram", "summary"}


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
    # Active series per `job` label value, per connection ("" for series without a job label).
    jobs: Mapping[str, Mapping[str, int]] = field(default_factory=dict)
    metric_type: str | None = None  # "counter", "gauge", "histogram"...; None when unknown
    recording_rule: bool = False  # made by a recording rule, not scraped
    # When a check first listed it; None when it was there before checks recorded this.
    first_seen: datetime | None = None


@dataclass(frozen=True)
class UnreadRecordingRule:
    """A recording rule whose output no dashboard, alert or watched rule reads, and that had no
    recent problem (one with problems is a blind spot: add it to Grafana, don't remove it)."""

    name: str
    groups: tuple[str, ...]
    connections: tuple[str, ...]  # where its output exists
    reads: tuple[str, ...]
    feeds: tuple[str, ...]  # other recording rules that read it, all of them unread too
    series: int | None
    analyzed: bool


@dataclass(frozen=True)
class MetricUsageReport:
    items: list[MetricReportItem]
    totals: dict[str, int | None]
    unread_rules: list[UnreadRecordingRule] = field(default_factory=list)


def metric_type(name: str, types: Mapping[str, str]) -> str | None:
    """The declared type of a metric (`types` from Prometheus metadata), else a guess from its name.
    A histogram's _bucket, _sum and _count series are listed under the histogram's base name."""
    if name in types:
        return types[name]
    for suffix in _FAMILY_SUFFIXES:
        if name.endswith(suffix) and types.get(name[: -len(suffix)]) in _FAMILY_TYPES:
            return types[name[: -len(suffix)]]
    if name.endswith("_total"):
        return "counter"
    if name.endswith("_bucket"):
        return "histogram"
    return None


def build_report(
    metrics_by_connection: Mapping[str, Iterable[str]],
    scan: UsageScan,
    problems: Mapping[str, tuple[int, int]] | None = None,
    analyzed: Iterable[str] = (),
    ignore_metrics: Iterable[str] = (),
    series_by_connection: Mapping[str, Mapping[str, int]] | None = None,
    jobs_by_connection: Mapping[str, Mapping[str, Mapping[str, int]]] | None = None,
    types: Mapping[str, str] | None = None,
    first_seen: Mapping[str, datetime | None] | None = None,
) -> MetricUsageReport:
    """`problems` maps a metric to (problem finding count, latest finding id); `series_by_connection`
    maps a connection to its active series per metric, where the backend could count them, and
    `jobs_by_connection` to its active series per metric and job label. `types` are declared metric types and
    `first_seen` when each metric was first listed."""
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

    def finds(usage: MetricUsage, metric: str) -> bool:
        present = connections.get(metric, [])
        return bool(present) and (usage.connections is None or any(connection in usage.connections for connection in present))

    def watching(metric: str) -> list[MetricUsage]:
        return [usage for usage in usages.get(metric, []) if usage.kind in WATCHING_KINDS]

    # Read by a dashboard or alert. Recording rules this reads become watched too, whether or not
    # the rule's output exists yet: an empty panel still means someone looks there.
    read = {metric for metric in usages if watching(metric)}
    watched = {metric for metric in read if any(finds(usage, metric) for usage in watching(metric))}
    via: dict[str, list[str]] = {}
    changed = True
    while changed:  # a watched recording rule makes the metrics it reads watched, through chains
        changed = False
        for rule_name, sources in scan.recording_rules.items():
            if rule_name not in watched and rule_name not in read:
                continue
            for source in sources:
                if rule_name not in via.setdefault(source, []):
                    via[source].append(rule_name)
                if source not in watched:
                    watched.add(source)
                    changed = True

    series_by_connection = series_by_connection or {}
    jobs_by_connection = jobs_by_connection or {}
    types = types or {}
    first_seen = first_seen or {}

    def jobs_of(metric: str) -> dict[str, dict[str, int]]:
        return {
            connection: dict(sorted(jobs_by_connection[connection][metric].items()))
            for connection in connections.get(metric, [])
            if metric in jobs_by_connection.get(connection, {})
        }

    def series_of(metric: str) -> int | None:
        counts = [series_by_connection[connection].get(metric, 0) for connection in connections.get(metric, []) if connection in series_by_connection]
        return sum(counts) if counts else None

    items: list[MetricReportItem] = []
    for metric in sorted(set(connections) | {name for name in read if not ignored(name)}):
        present = metric in connections
        count, latest = problems.get(metric, (0, None))
        if present and metric in watched:
            status = "watched"
        elif present and count:
            status = "blind_spot"
        elif metric in read:
            status = "missing"  # every dashboard and alert reading it comes up empty
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
                jobs=jobs_of(metric),
                metric_type=metric_type(metric, types),
                recording_rule=metric in scan.recording_rules,
                first_seen=first_seen.get(metric),
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

    unread = [
        name for name in scan.recording_rules
        if name not in watched and name not in read and not ignored(name) and not (name in connections and problems.get(name, (0, None))[0])
    ]
    unread_rules = [
        UnreadRecordingRule(
            name=name,
            groups=tuple(sorted(scan.recording_rule_groups.get(name, ()))),
            connections=tuple(connections.get(name, [])),
            reads=tuple(sorted(scan.recording_rules[name])),
            feeds=tuple(sorted(other for other, sources in scan.recording_rules.items() if name in sources)),
            series=series_of(name) if name in connections else None,
            analyzed=name in analyzed,
        )
        for name in unread
    ]
    unread_rules.sort(key=lambda rule: (-(rule.series or 0), rule.name))
    return MetricUsageReport(items, totals, unread_rules)
