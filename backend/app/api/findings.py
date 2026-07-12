from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.api_schema import FindingOut
from backend.app.models.db import get_db
from backend.app.models.entities import FindingEntity

router = APIRouter(prefix="/api/findings", tags=["findings"])


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
    rows = db.execute(query.order_by(FindingEntity.importance_score.desc())).scalars().all()
    return [_to_finding_out(row) for row in rows]


@router.get("/{finding_id}", response_model=FindingOut)
def get_finding(finding_id: int, db: Session = Depends(get_db)) -> FindingOut:
    row = db.execute(select(FindingEntity).where(FindingEntity.id == finding_id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="finding not found")
    return _to_finding_out(row)
