from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.config import get_metric_usage_config
from backend.app.integrations.grafana.client import GrafanaClient, GrafanaError
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
        items = [_item_out(row) for row in rows]
    return MetricUsageOut(
        enabled=config.enabled,
        interval_hours=config.interval_hours,
        grafana_configured=config.grafana.configured,
        snapshot=_snapshot_out(snapshot) if snapshot else None,
        last_failure=_snapshot_out(latest) if latest is not None and latest.status == "failed" else None,
        items=items,
        items_total=total,
        cost=_cost(config.cost_per_1k_series_month, config.currency, snapshot),
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
    return {row.metric_name: _item_out(row) for row in rows}


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
    )
