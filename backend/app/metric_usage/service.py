"""Run a metric usage check: read what watches metrics (Grafana dashboards and alert rules,
Prometheus/Mimir rules), list every metric each Prometheus connection has, join with recent
findings, and store the result as a snapshot.

A check that can't read Grafana fails rather than saving a half-read result - with the
dashboards missing, every metric would look unwatched.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.app.config import MetricUsageConfig, get_metric_usage_config, get_prometheus_connections
from backend.app.integrations.grafana.client import GrafanaClient, GrafanaError
from backend.app.metric_usage.report import MetricUsageReport, build_report
from backend.app.metric_usage.sources import (
    DatasourceIndex,
    UsageScan,
    dashboard_usages,
    datasource_scopes,
    folder_excluded,
    grafana_alert_rule_usages,
    prometheus_rule_usages,
    walk_panels,
)
from backend.app.models.entities import (
    AutonomousMetricJobEntity,
    FindingEntity,
    MetricUsageItemEntity,
    MetricUsageSnapshotEntity,
)
from backend.app.services.prometheus_service import PrometheusQueryService

logger = logging.getLogger(__name__)

PROBLEM_STATUSES = ("significant", "critical")
ANALYZED_WINDOW = timedelta(days=7)
# Metric names are listed over this window, so long-retention backends don't return years of
# metrics that no longer exist.
METRIC_NAMES_WINDOW = timedelta(hours=24)

_running = threading.Lock()


class CheckAlreadyRunning(RuntimeError):
    pass


def run_configured_check(db: Session, *, trigger: str, config: MetricUsageConfig | None = None) -> MetricUsageSnapshotEntity:
    config = config or get_metric_usage_config()
    grafana = GrafanaClient(config.grafana) if config.grafana.configured else None
    prometheus = {connection.id: PrometheusQueryService(connection) for connection in get_prometheus_connections().connections if connection.base_url}
    return run_check(db, config, grafana=grafana, prometheus=prometheus, trigger=trigger)


def run_check(
    db: Session,
    config: MetricUsageConfig,
    *,
    grafana: GrafanaClient | None,
    prometheus: Mapping[str, PrometheusQueryService],
    trigger: str,
    now: datetime | None = None,
) -> MetricUsageSnapshotEntity:
    if not _running.acquire(blocking=False):
        raise CheckAlreadyRunning("A metric usage check is already running")
    try:
        now = now or datetime.now(timezone.utc)
        started = time.perf_counter()
        snapshot = MetricUsageSnapshotEntity(id=uuid4().hex, trigger=trigger, created_at=now)
        try:
            scan, sources = _collect_usage(grafana, prometheus, config.exclude_folders)
            metrics_by_connection = _metric_names(prometheus, now, sources)
            series_by_connection = _series_counts(prometheus, metrics_by_connection, sources)
            report = build_report(
                metrics_by_connection,
                scan,
                problems=_recent_problems(db, now - timedelta(hours=config.problem_window_hours)),
                analyzed=_analyzed_metrics(db, now - ANALYZED_WINDOW),
                ignore_metrics=config.ignore_metrics,
                series_by_connection=series_by_connection,
            )
        except (GrafanaError, HTTPException, ValueError) as exc:
            snapshot.status = "failed"
            snapshot.error = str(getattr(exc, "detail", None) or exc)
            snapshot.duration_ms = int((time.perf_counter() - started) * 1000)
            logger.warning("Metric usage check failed: %s", snapshot.error)
            db.add(snapshot)
            db.commit()
            return snapshot

        _fill_snapshot(snapshot, report, sources)
        snapshot.duration_ms = int((time.perf_counter() - started) * 1000)
        db.add(snapshot)
        # The entities have no relationship() between them, so the session doesn't know to insert
        # the snapshot first; Postgres rejects items whose snapshot row doesn't exist yet.
        db.flush()
        db.add_all(_items(snapshot.id, report))
        db.commit()
        _prune(db, config.keep_snapshots)
        return snapshot
    finally:
        _running.release()


def check_is_due(db: Session, config: MetricUsageConfig, now: datetime | None = None) -> bool:
    if not config.enabled:
        return False
    now = now or datetime.now(timezone.utc)
    latest = db.scalar(select(func.max(MetricUsageSnapshotEntity.created_at)))
    if latest is None:
        return True
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    return latest <= now - timedelta(hours=config.interval_hours)


def run_scheduled_check_if_due(db: Session) -> None:
    """Called from the scheduler loop every minute; a no-op until the interval has passed."""
    config = get_metric_usage_config()
    if not check_is_due(db, config):
        return
    try:
        snapshot = run_configured_check(db, trigger="schedule", config=config)
    except CheckAlreadyRunning:
        return
    logger.info("Metric usage check %s: %s", snapshot.id, snapshot.status)


def latest_snapshot(db: Session, *, completed_only: bool = False) -> MetricUsageSnapshotEntity | None:
    query = select(MetricUsageSnapshotEntity)
    if completed_only:
        query = query.where(MetricUsageSnapshotEntity.status == "completed")
    return db.scalars(query.order_by(MetricUsageSnapshotEntity.created_at.desc()).limit(1)).first()


def _collect_usage(grafana: GrafanaClient | None, prometheus: Mapping[str, PrometheusQueryService], exclude_folders: list[str]) -> tuple[UsageScan, dict]:
    scan = UsageScan()
    warnings: list[str] = []
    sources: dict = {"grafana": {"configured": grafana is not None}, "prometheus": [], "warnings": warnings}

    if grafana is not None:
        try:
            index = datasource_scopes(grafana.datasources(), [service.config for service in prometheus.values()])
        except GrafanaError as exc:
            # Listing datasources needs more than the Viewer role on some Grafana versions.
            index = DatasourceIndex({}, {}, {})
            warnings.append(f"Couldn't list Grafana datasources ({exc}); queries are assumed to be Prometheus unless their panel says otherwise.")
        folder_titles = grafana.folder_titles()
        library: dict[str, dict] = {}
        read, excluded = 0, []
        for item in grafana.list_dashboards():
            if folder_excluded(item.get("folderTitle"), exclude_folders):
                excluded.append(f"{item.get('folderTitle')} / {item.get('title')}")
                continue
            try:
                payload = grafana.get_dashboard(item["uid"])
            except GrafanaError as exc:
                if exc.status != 404:
                    raise
                warnings.append(f"Dashboard {item.get('title')} disappeared during the check")
                continue
            for panel in walk_panels(payload.get("dashboard") or {}):
                uid = (panel.get("libraryPanel") or {}).get("uid")
                if uid and uid not in library:
                    try:
                        library[uid] = grafana.library_panel(uid)
                    except GrafanaError as exc:
                        library[uid] = {}
                        warnings.append(f"Couldn't read library panel {uid}: {exc}")
            scan.merge(dashboard_usages(payload, library_panels=library, datasource_types=index.types, datasource_scopes=index.scopes))
            read += 1

        try:
            rules = grafana.alert_rules()
        except GrafanaError as exc:
            rules = []
            warnings.append(f"Couldn't read Grafana alert rules: {exc}")
        rules = [rule for rule in rules if not folder_excluded(folder_titles.get(rule.get("folderUID") or ""), exclude_folders)]
        scan.merge(grafana_alert_rule_usages(rules, folder_titles=folder_titles, datasource_types=index.types, datasource_scopes=index.scopes))
        sources["grafana"].update(dashboards_read=read, dashboards_excluded=excluded, alert_rules_read=len(rules))
        if scan.skipped_datasources:
            skipped = sorted({index.names.get(key, key) for key in scan.skipped_datasources})
            sources["grafana"]["datasources_skipped"] = skipped
            warnings.append(
                f"Panels and alerts on {', '.join(skipped)} were left out: no Prometheus connection matches "
                "that datasource's URL. If one reads the same data, add the datasource's uid or name under "
                "grafana_datasources in the connections file."
            )

    for connection_id, service in prometheus.items():
        entry = {"id": connection_id, "name": service.config.name, "rule_groups": 0}
        try:
            payload = service.rules()
            entry["rule_groups"] = len((payload.get("data") or {}).get("groups") or [])
            scan.merge(prometheus_rule_usages(payload, connection_id))
        except HTTPException as exc:
            warnings.append(f"Couldn't read rules from {service.config.name}: {exc.detail}")
        sources["prometheus"].append(entry)

    sources["unresolved_queries"] = [{"location": item.location, "variables": sorted(item.variables)} for item in scan.unresolved]
    sources["name_patterns"] = [{"pattern": pattern, "location": location} for pattern, location in scan.name_patterns]
    return scan, sources


def _metric_names(prometheus: Mapping[str, PrometheusQueryService], now: datetime, sources: dict) -> dict[str, list[str]]:
    if not prometheus:
        raise ValueError("No Prometheus connection is configured")
    names: dict[str, list[str]] = {}
    errors: list[str] = []
    entries = {entry["id"]: entry for entry in sources["prometheus"]}
    for connection_id, service in prometheus.items():
        try:
            names[connection_id] = service.label_values("__name__", start=now - METRIC_NAMES_WINDOW, end=now)
        except HTTPException as exc:
            errors.append(f"{service.config.name}: {exc.detail}")
            continue
        entries[connection_id]["metrics"] = len(names[connection_id])
    if not names:
        raise ValueError(f"Couldn't list metrics from any Prometheus connection ({'; '.join(errors)})")
    sources["warnings"].extend(f"Couldn't list metrics from {error}" for error in errors)
    return names


def _series_counts(prometheus: Mapping[str, PrometheusQueryService], metrics_by_connection: Mapping[str, list[str]], sources: dict) -> dict[str, dict[str, int]]:
    """Active series per metric, per connection. Optional: a backend that refuses the count (too
    many series for its query limits) leaves that connection's series unknown, with a warning."""
    counts: dict[str, dict[str, int]] = {}
    for connection_id in metrics_by_connection:
        service = prometheus[connection_id]
        try:
            counts[connection_id] = service.series_counts_by_name()
        except HTTPException as exc:
            sources["warnings"].append(f"Couldn't count series in {service.config.name}: {exc.detail}")
    return counts


def _recent_problems(db: Session, since: datetime) -> dict[str, tuple[int, int]]:
    rows = db.execute(
        select(FindingEntity.metric_name, func.count(FindingEntity.id), func.max(FindingEntity.id))
        .where(FindingEntity.created_at >= since, FindingEntity.health_status.in_(PROBLEM_STATUSES))
        .group_by(FindingEntity.metric_name)
    ).all()
    return {name: (int(count), int(latest)) for name, count, latest in rows}


def _analyzed_metrics(db: Session, since: datetime) -> set[str]:
    """Metrics Ops Signals analysed recently: a completed autonomous job, or any finding (alert
    enrichment and OTLP analysis create findings without autonomous jobs)."""
    jobs = db.scalars(
        select(AutonomousMetricJobEntity.metric_name)
        .where(AutonomousMetricJobEntity.status == "completed", AutonomousMetricJobEntity.created_at >= since)
        .distinct()
    ).all()
    findings = db.scalars(select(FindingEntity.metric_name).where(FindingEntity.created_at >= since).distinct()).all()
    return set(jobs) | set(findings)


def _fill_snapshot(snapshot: MetricUsageSnapshotEntity, report: MetricUsageReport, sources: dict) -> None:
    snapshot.status = "completed"
    snapshot.metrics_total = report.totals["metrics"]
    snapshot.watched = report.totals["watched"]
    snapshot.blind_spots = report.totals["blind_spots"]
    snapshot.unwatched = report.totals["unwatched"]
    snapshot.missing = report.totals["missing"]
    snapshot.series_total = report.totals["series_total"]
    snapshot.series_unwatched = report.totals["series_unwatched"]
    snapshot.sources_json = sources


def _items(snapshot_id: str, report: MetricUsageReport) -> list[MetricUsageItemEntity]:
    return [
        MetricUsageItemEntity(
            snapshot_id=snapshot_id,
            metric_name=item.metric,
            status=item.status,
            connections_json=list(item.connections),
            usages_json=[
                {"kind": usage.kind, "location": usage.location, "folder": usage.folder, "dashboard_uid": usage.dashboard_uid}
                for usage in item.usages
            ],
            via_recording_rules_json=list(item.via_recording_rules),
            problem_findings=item.problem_findings,
            latest_finding_id=item.latest_finding_id,
            analyzed=item.analyzed,
            series=item.series,
        )
        for item in report.items
    ]


def _prune(db: Session, keep: int) -> None:
    old_ids = db.scalars(
        select(MetricUsageSnapshotEntity.id).order_by(MetricUsageSnapshotEntity.created_at.desc()).offset(max(keep, 1))
    ).all()
    if not old_ids:
        return
    # Items first: SQLite doesn't cascade without the foreign_keys pragma.
    db.execute(delete(MetricUsageItemEntity).where(MetricUsageItemEntity.snapshot_id.in_(old_ids)))
    db.execute(delete(MetricUsageSnapshotEntity).where(MetricUsageSnapshotEntity.id.in_(old_ids)))
    db.commit()
