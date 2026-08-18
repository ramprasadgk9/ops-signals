from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.app.models.api_schema import FindingOut
from backend.app.models.db import get_db
from backend.app.models.entities import FindingEntity

router = APIRouter(prefix="/api/findings", tags=["findings"])
Window = Literal["1h", "6h", "24h", "7d"]


def _window_start(window: Window) -> datetime:
    now = datetime.now(timezone.utc)
    if window == "1h":
        return now - timedelta(hours=1)
    if window == "6h":
        return now - timedelta(hours=6)
    if window == "7d":
        return now - timedelta(days=7)
    return now - timedelta(hours=24)


def _to_finding_out(finding: FindingEntity) -> FindingOut:
    return FindingOut(
        id=finding.id,
        service=finding.service,
        metric_name=finding.metric_name,
        title=finding.title,
        summary=finding.summary,
        category=finding.category,
        health_status=finding.health_status,
        importance_score=finding.importance_score,
        investigation_priority=finding.investigation_priority,
        signal_ids=finding.signal_ids,
        comparison_json=finding.comparison_json or {},
        analysis_run_id=finding.analysis_run_id,
        created_at=finding.created_at,
    )


@router.get("", response_model=list[FindingOut])
def list_findings(
    service: str | None = None,
    metric_name: str | None = None,
    health_status: str | None = None,
    category: str | None = None,
    analysis_run_id: str | None = Query(default=None),
    window: Window | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[FindingOut]:
    query = select(FindingEntity)
    if service:
        query = query.where(FindingEntity.service == service)
    if metric_name:
        query = query.where(FindingEntity.metric_name == metric_name)
    if health_status:
        query = query.where(FindingEntity.health_status == health_status)
    if category:
        query = query.where(FindingEntity.category == category)
    if analysis_run_id:
        query = query.where(FindingEntity.analysis_run_id == analysis_run_id)
    if window:
        query = query.where(FindingEntity.created_at >= _window_start(window))
    rows = db.execute(query.order_by(FindingEntity.importance_score.desc())).scalars().all()
    return [_to_finding_out(row) for row in rows]


@router.get("/search", response_model=list[FindingOut])
def search_findings(
    q: str | None = Query(default=None, description="Optional text search across title, summary, service, metric, and category."),
    service: str | None = None,
    metric_name: str | None = None,
    health_status: str | None = None,
    category: str | None = None,
    analysis_run_id: str | None = Query(default=None),
    window: Window = Query(default="24h"),
    limit: int = Query(default=25, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[FindingOut]:
    query = select(FindingEntity).where(FindingEntity.created_at >= _window_start(window))
    if service:
        query = query.where(FindingEntity.service == service)
    if metric_name:
        query = query.where(FindingEntity.metric_name == metric_name)
    if health_status:
        query = query.where(FindingEntity.health_status == health_status)
    if category:
        query = query.where(FindingEntity.category == category)
    if analysis_run_id:
        query = query.where(FindingEntity.analysis_run_id == analysis_run_id)
    if q:
        pattern = f"%{q.strip().lower()}%"
        query = query.where(
            or_(
                func.lower(FindingEntity.title).like(pattern),
                func.lower(FindingEntity.summary).like(pattern),
                func.lower(FindingEntity.service).like(pattern),
                func.lower(FindingEntity.metric_name).like(pattern),
                func.lower(FindingEntity.category).like(pattern),
            )
        )
    rows = db.execute(query.order_by(FindingEntity.importance_score.desc(), FindingEntity.created_at.desc()).limit(limit)).scalars().all()
    return [_to_finding_out(row) for row in rows]


@router.get("/{finding_id}", response_model=FindingOut)
def get_finding(finding_id: int, db: Session = Depends(get_db)) -> FindingOut:
    row = db.execute(select(FindingEntity).where(FindingEntity.id == finding_id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="finding not found")
    return _to_finding_out(row)
