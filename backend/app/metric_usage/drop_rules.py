"""Which unused metrics may be dropped, and the Prometheus scrape config that drops them.

Only whole metrics, by name (`action: drop` on `__name__`): dropping single labels would merge
series and corrupt the data that's left. Nothing is applied - the user copies the config into
their own scrape jobs, under the job that collects each metric (`metric_relabel_configs` is set
per job). Jobs are known by the series' `job` label, which is usually the scrape config's
job_name but not always (relabeling, prometheus-operator), so the config says so. Series with no
job label weren't scraped by a job the config can name and aren't counted as dropped.

A metric is never offered when something reads it, Ops Signals found problems on it, a recording
rule makes it (remove the rule instead), Prometheus makes it itself, it's new (its dashboard may
not exist yet), or the job that collects it isn't known. Metrics Ops Signals analyzes, or that a
dashboard query may match by a name pattern, can be dropped with a warning.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# A new metric gets this long before Drop is offered, so its team has time to build the dashboard.
NEW_METRIC_GRACE = timedelta(days=7)
_METRIC_NAME = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
# Made by Prometheus for every target or rule, not by any exporter, so a scrape rule can't drop them.
_PROMETHEUS_MADE = re.compile(r"^(up|scrape_[a-z_]+|ALERTS|ALERTS_FOR_STATE)$")


@dataclass(frozen=True)
class DropCheck:
    blocked: str | None  # why Drop isn't offered; None when it is
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConfigBlock:
    connection: str
    name: str
    yaml: str


@dataclass(frozen=True)
class DropConfig:
    # One per Prometheus connection: each goes into that server's own prometheus.yml.
    blocks: list[ConfigBlock]
    metrics: list[str]
    series: int | None
    skipped: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


_JOB_NOTE = (
    "# Each rule goes under the scrape job whose series carry that job label - usually the job_name\n"
    "# shown. With relabeling or prometheus-operator the job_name differs: put the rule in that job\n"
    "# (or the ServiceMonitor's metricRelabelings).\n"
)


def compile_patterns(patterns: Iterable[Mapping]) -> list[tuple[re.Pattern[str], str]]:
    """Name regexes (`{__name__=~"..."}`) dashboards and rules read metrics by, compiled once;
    ones Python can't compile are skipped."""
    compiled = []
    for item in patterns:
        try:
            compiled.append((re.compile(str(item.get("pattern") or "")), str(item.get("location") or "")))
        except re.error:
            continue
    return compiled


def name_pattern_matches(metric: str, patterns: Iterable[tuple[re.Pattern[str], str]]) -> list[str]:
    """Where a query reads metrics by a name regex that matches this one. PromQL regexes are
    anchored at both ends."""
    return [location for pattern, location in patterns if pattern.fullmatch(metric)]


def scraped_series(jobs: Mapping[str, Mapping[str, int]]) -> tuple[int, int]:
    """(series under a job label, series without one) over all connections."""
    labelled = sum(count for by_job in jobs.values() for job, count in by_job.items() if job)
    unlabelled = sum(count for by_job in jobs.values() for job, count in by_job.items() if not job)
    return labelled, unlabelled


def drop_check(
    *,
    metric: str,
    status: str,
    recording_rule: bool,
    jobs: Mapping[str, Mapping[str, int]],
    first_seen: datetime | None,
    analyzed: bool,
    pattern_locations: list[str],
    now: datetime,
) -> DropCheck:
    if status == "blind_spot":
        return DropCheck("Ops Signals found problems on it. Add it to Grafana instead.")
    if status != "unwatched":
        return DropCheck("A dashboard or alert reads it.")
    if recording_rule:
        return DropCheck("A recording rule makes it. Remove the rule instead (see Recording rules nobody reads).")
    if _PROMETHEUS_MADE.match(metric) or not _METRIC_NAME.match(metric):
        return DropCheck("Prometheus makes it itself, so a scrape rule can't drop it.")
    if first_seen is not None:
        first_seen = first_seen if first_seen.tzinfo else first_seen.replace(tzinfo=timezone.utc)
        if now - first_seen < NEW_METRIC_GRACE:
            days = max(1, math.ceil((NEW_METRIC_GRACE - (now - first_seen)) / timedelta(days=1)))
            return DropCheck(f"First seen {_ago(now - first_seen)}. Drop is offered in {days} {'day' if days == 1 else 'days'}, so its team has time to build a dashboard.")
    labelled, unlabelled = scraped_series(jobs)
    if not any(job for by_job in jobs.values() for job in by_job):
        return DropCheck("Couldn't tell which scrape job collects it: its series couldn't be counted, or have no job label.")
    warnings = []
    if unlabelled:
        warnings.append(
            f"{unlabelled:,} of its {labelled + unlabelled:,} series have no job label (sent by remote write or OTLP?). "
            "A scrape rule won't drop those; drop them where they're sent from."
        )
    if analyzed:
        warnings.append("Ops Signals analyzes this metric. Dropping it stops that analysis.")
    if pattern_locations:
        warnings.append(f"A query reads metrics by a name pattern that matches it: {', '.join(pattern_locations[:2])}. Check it before dropping.")
    return DropCheck(None, tuple(warnings))


def build_drop_config(
    items: Iterable[Mapping],
    *,
    connection_names: Mapping[str, str],
    checked_on: datetime,
) -> DropConfig:
    """`items` are the selected metrics, each with `metric`, `jobs` (series per job label, per
    connection) and `check` (a DropCheck). Blocked ones are skipped with their reason. `series`
    counts only what the rules drop: series under a job label."""
    # connection -> job -> metrics
    plan: dict[str, dict[str, list[str]]] = {}
    chosen: list[str] = []
    skipped: list[dict[str, str]] = []
    warnings: list[str] = []
    series = 0
    counted = False
    for item in items:
        check: DropCheck = item["check"]
        if check.blocked:
            skipped.append({"metric": item["metric"], "reason": check.blocked})
            continue
        chosen.append(item["metric"])
        warnings.extend(f"{item['metric']}: {warning}" for warning in check.warnings)
        jobs = item.get("jobs") or {}
        if jobs:
            series += scraped_series(jobs)[0]
            counted = True
        for connection, by_job in jobs.items():
            for job in by_job:
                if job:
                    plan.setdefault(connection, {}).setdefault(job, []).append(item["metric"])

    stamp = checked_on.date().isoformat()
    blocks: list[ConfigBlock] = []
    for connection in sorted(plan, key=lambda key: connection_names.get(key, key)):
        lines = [_JOB_NOTE + "scrape_configs:"]
        for job in sorted(plan[connection]):
            names = sorted(set(plan[connection][job]))
            lines += [
                f"  - job_name: {_yaml_string(job)}",
                "    metric_relabel_configs:",
                f"      # Ops Signals: not used by any dashboard or rule ({stamp})",
                "      - source_labels: [__name__]",
                f"        regex: '{'|'.join(names)}'",
                "        action: drop",
                "",
            ]
        blocks.append(ConfigBlock(connection, connection_names.get(connection, connection), "\n".join(lines).rstrip() + "\n"))
    return DropConfig(
        blocks=blocks,
        metrics=chosen,
        series=series if counted else None,
        skipped=skipped,
        warnings=warnings,
    )


def _yaml_string(value: str) -> str:
    """A job name as YAML: plain when that's unambiguous, else single-quoted."""
    if re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_./-]*", value) and value.lower() not in {"true", "false", "null", "yes", "no", "on", "off", "~"}:
        return value
    return "'" + value.replace("'", "''") + "'"


def _ago(delta: timedelta) -> str:
    days = delta.days
    if days < 1:
        return "today"
    return "yesterday" if days == 1 else f"{days} days ago"
