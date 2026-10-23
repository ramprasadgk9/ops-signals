from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.config import get_metric_usage_config, get_prometheus_connections
from backend.app.integrations.grafana.client import GrafanaClient, GrafanaError
from backend.app.metric_usage.drop_rules import DropCheck, build_drop_config, compile_patterns, drop_check, name_pattern_matches
from backend.app.metric_usage.service import CheckAlreadyRunning, latest_snapshot, run_configured_check
from backend.app.models.db import get_db
from backend.app.models.entities import MetricUsageItemEntity, MetricUsageSnapshotEntity

router = APIRouter(prefix="/api/metric-usage", tags=["metric-usage"])

STATUSES = ("blind_spot", "missing", "watched", "unwatched")


class SnapshotOut(BaseModel):
    id: str
    trigger: str
    status: str
    created_at: datetime
    duration_ms: int | None
    error: str | None
    metrics_total: int
    watched: int
    blind_spots: int
    unwatched: int
    missing: int
    watched_percent: float | None
    series_total: int | None
    series_unwatched: int | None
    sources: dict


class CostOut(BaseModel):
    """Monthly storage cost at the rate the operator configured; None amounts when series couldn't be counted."""

    per_1k_series_month: float
    currency: str
    unwatched_monthly: float | None
    total_monthly: float | None


class UsageOut(BaseModel):
    kind: str
    location: str
    folder: str | None = None
    dashboard_uid: str | None = None


class MetricItemOut(BaseModel):
    metric: str
    status: str
    connections: list[str]
    usages: list[UsageOut]
    via_recording_rules: list[str]
    problem_findings: int
    latest_finding_id: int | None
    analyzed: bool
    series: int | None
    # Active series per job label, per connection ("" for series without one).
    jobs: dict[str, dict[str, int]] = {}
    metric_type: str | None = None
    recording_rule: bool = False
    first_seen: datetime | None = None
    # Why Drop isn't offered for it (None when it is), and what to check before dropping it.
    drop_blocked: str | None = None
    drop_warnings: list[str] = []


class UnreadRuleOut(BaseModel):
    name: str
    groups: list[str]
    connections: list[str]
    reads: list[str]
    feeds: list[str]
    series: int | None
    analyzed: bool
    # What to check before removing it.
    warnings: list[str] = []


class DropConfigIn(BaseModel):
    metrics: list[str] = Field(min_length=1, max_length=1000)


class ConfigBlockOut(BaseModel):
    connection: str
    name: str
    yaml: str


class DropConfigOut(BaseModel):
    # One per Prometheus connection: each goes into that server's own config.
    blocks: list[ConfigBlockOut]
    metrics: list[str]
    series: int | None
    skipped: list[dict[str, str]]
    warnings: list[str]


class MetricUsageOut(BaseModel):
    enabled: bool
    interval_hours: float
    grafana_configured: bool
    snapshot: SnapshotOut | None
    # The latest check, when it failed: `snapshot` then still shows the last good one.
    last_failure: SnapshotOut | None
    items: list[MetricItemOut]
    items_total: int
    # Only when OPS_SIGNALS_METRIC_USAGE_COST_PER_1K_SERIES is set.
    cost: CostOut | None = None
    unread_rules: list[UnreadRuleOut] = []


class GrafanaStatusOut(BaseModel):
    configured: bool
    url: str | None
    reachable: bool
    version: str | None = None
    message: str


@router.get("", response_model=MetricUsageOut)
def get_metric_usage(
    status: list[str] = Query(default=[]),
    q: str | None = Query(default=None, description="Metric name contains"),
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> MetricUsageOut:
    config = get_metric_usage_config()
    snapshot = latest_snapshot(db, completed_only=True)
    latest = latest_snapshot(db)
    items: list[MetricItemOut] = []
    total = 0
    if snapshot is not None:
        query = select(MetricUsageItemEntity).where(MetricUsageItemEntity.snapshot_id == snapshot.id)
        if status:
            query = query.where(MetricUsageItemEntity.status.in_(status))
        if q:
            query = query.where(MetricUsageItemEntity.metric_name.contains(q.strip()))
        total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = db.scalars(query.order_by(MetricUsageItemEntity.id).offset(offset).limit(limit)).all()
        items = _items_out(rows, snapshot)
    return MetricUsageOut(
        enabled=config.enabled,
        interval_hours=config.interval_hours,
        grafana_configured=config.grafana.configured,
        snapshot=_snapshot_out(snapshot) if snapshot else None,
        last_failure=_snapshot_out(latest) if latest is not None and latest.status == "failed" else None,
        items=items,
        items_total=total,
        cost=_cost(config.cost_per_1k_series_month, config.currency, snapshot),
        unread_rules=_unread_rules_out(snapshot) if snapshot else [],
    )


@router.get("/history", response_model=list[SnapshotOut])
def get_metric_usage_history(limit: int = Query(default=28, ge=1, le=200), db: Session = Depends(get_db)) -> list[SnapshotOut]:
    rows = db.scalars(select(MetricUsageSnapshotEntity).order_by(MetricUsageSnapshotEntity.created_at.desc()).limit(limit)).all()
    return [_snapshot_out(row) for row in rows]


@router.get("/metrics", response_model=dict[str, MetricItemOut])
def lookup_metrics(name: list[str] = Query(default=[]), db: Session = Depends(get_db)) -> dict[str, MetricItemOut]:
    """The latest status of a few metrics by name - for tagging findings with who watches them."""
    snapshot = latest_snapshot(db, completed_only=True)
    if snapshot is None or not name:
        return {}
    rows = db.scalars(
        select(MetricUsageItemEntity).where(MetricUsageItemEntity.snapshot_id == snapshot.id, MetricUsageItemEntity.metric_name.in_(name[:500]))
    ).all()
    return {item.metric: item for item in _items_out(rows, snapshot)}


@router.post("/drop-config", response_model=DropConfigOut)
def drop_config(body: DropConfigIn, db: Session = Depends(get_db)) -> DropConfigOut:
    """Prometheus scrape config that stops storing the given unused metrics. Changes nothing:
    the user copies it into their own scrape jobs."""
    snapshot = latest_snapshot(db, completed_only=True)
    if snapshot is None:
        raise HTTPException(status_code=409, detail="No metric usage check has completed yet.")
    wanted = list(dict.fromkeys(body.metrics))
    rows = db.scalars(
        select(MetricUsageItemEntity).where(MetricUsageItemEntity.snapshot_id == snapshot.id, MetricUsageItemEntity.metric_name.in_(wanted))
    ).all()
    found = {item.metric: item for item in _items_out(rows, snapshot)}
    selected = []
    for name in wanted:
        item = found.get(name)
        if item is None:
            selected.append({"metric": name, "check": DropCheck("The latest check didn't list it.")})
            continue
        selected.append({"metric": name, "series": item.series, "jobs": item.jobs, "check": DropCheck(item.drop_blocked, tuple(item.drop_warnings))})
    names = {connection.id: connection.name for connection in get_prometheus_connections().connections}
    config = build_drop_config(selected, connection_names=names, checked_on=snapshot.created_at)
    return DropConfigOut(
        blocks=[ConfigBlockOut(connection=block.connection, name=block.name, yaml=block.yaml) for block in config.blocks],
        metrics=config.metrics, series=config.series, skipped=config.skipped, warnings=config.warnings,
    )


@router.post("/run", response_model=SnapshotOut)
def run_metric_usage_check(db: Session = Depends(get_db)) -> SnapshotOut:
    try:
        snapshot = run_configured_check(db, trigger="manual")
    except CheckAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _snapshot_out(snapshot)


@router.get("/grafana/status", response_model=GrafanaStatusOut)
def grafana_status() -> GrafanaStatusOut:
    config = get_metric_usage_config().grafana
    if not config.configured:
        return GrafanaStatusOut(configured=False, url=None, reachable=False, message="Grafana is not connected. Set OPS_SIGNALS_GRAFANA_URL and a token.")
    try:
        version = GrafanaClient(config).check()
    except GrafanaError as exc:
        return GrafanaStatusOut(configured=True, url=config.base_url, reachable=False, message=str(exc))
    return GrafanaStatusOut(configured=True, url=config.base_url, reachable=True, version=version or None, message="Connected")


def _cost(rate: float | None, currency: str, snapshot: MetricUsageSnapshotEntity | None) -> CostOut | None:
    if rate is None:
        return None

    def monthly(series: int | None) -> float | None:
        return round(series / 1000 * rate, 2) if series is not None else None

    return CostOut(
        per_1k_series_month=rate,
        currency=currency,
        unwatched_monthly=monthly(snapshot.series_unwatched if snapshot else None),
        total_monthly=monthly(snapshot.series_total if snapshot else None),
    )


def _snapshot_out(row: MetricUsageSnapshotEntity) -> SnapshotOut:
    return SnapshotOut(
        id=row.id,
        trigger=row.trigger,
        status=row.status,
        created_at=row.created_at,
        duration_ms=row.duration_ms,
        error=row.error,
        metrics_total=row.metrics_total,
        watched=row.watched,
        blind_spots=row.blind_spots,
        unwatched=row.unwatched,
        missing=row.missing,
        watched_percent=round(100 * row.watched / row.metrics_total, 1) if row.metrics_total else None,
        series_total=row.series_total,
        series_unwatched=row.series_unwatched,
        sources=row.sources_json or {},
    )


def _patterns(snapshot: MetricUsageSnapshotEntity):
    return compile_patterns((snapshot.sources_json or {}).get("name_patterns") or [])


def _unread_rules_out(snapshot: MetricUsageSnapshotEntity) -> list[UnreadRuleOut]:
    patterns = _patterns(snapshot)
    rules = []
    for rule in snapshot.unread_rules_json or []:
        warnings = []
        if rule.get("analyzed"):
            warnings.append("Ops Signals analyzes its output. Removing it stops that analysis.")
        locations = name_pattern_matches(rule["name"], patterns)
        if locations:
            warnings.append(f"A query reads metrics by a name pattern that matches it: {', '.join(locations[:2])}. Check it before removing.")
        rules.append(UnreadRuleOut(**{key: value for key, value in rule.items() if key != "warnings"}, warnings=warnings))
    return rules


def _items_out(rows: Iterable[MetricUsageItemEntity], snapshot: MetricUsageSnapshotEntity) -> list[MetricItemOut]:
    patterns = _patterns(snapshot)
    now = datetime.now(timezone.utc)
    items = []
    for row in rows:
        item = _item_out(row)
        check = drop_check(
            metric=item.metric, status=item.status, recording_rule=item.recording_rule, jobs=item.jobs, first_seen=item.first_seen,
            analyzed=item.analyzed, pattern_locations=name_pattern_matches(item.metric, patterns), now=now,
        )
        item.drop_blocked, item.drop_warnings = check.blocked, list(check.warnings)
        items.append(item)
    return items


def _item_out(row: MetricUsageItemEntity) -> MetricItemOut:
    return MetricItemOut(
        metric=row.metric_name,
        status=row.status,
        connections=row.connections_json or [],
        usages=[UsageOut(**usage) for usage in row.usages_json or []],
        via_recording_rules=row.via_recording_rules_json or [],
        problem_findings=row.problem_findings,
        latest_finding_id=row.latest_finding_id,
        analyzed=row.analyzed,
        series=row.series,
        # Checks from before per-job counts stored job names only: unknown until the next check.
        jobs={connection: jobs for connection, jobs in (row.jobs_json or {}).items() if isinstance(jobs, dict)},
        metric_type=row.metric_type,
        recording_rule=bool(row.recording_rule),
        first_seen=row.first_seen,
    )
