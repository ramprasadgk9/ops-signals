from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.api_schema import AnalyzerLearningOutcomeOut, LearningOutcomeCreateRequest
from backend.app.models.db import get_db
from backend.app.models.entities import AnalyzerLearningOutcomeEntity
from backend.app.services.analyzer_learning_service import AnalyzerLearningService, LearningOutcomeError

router = APIRouter(prefix="/api", tags=["learning-outcomes"])


def _to_outcome_out(record: AnalyzerLearningOutcomeEntity) -> AnalyzerLearningOutcomeOut:
    return AnalyzerLearningOutcomeOut(
        id=record.id,
        organization_id=record.organization_id,
        service_id=record.service_id,
        metric_name=record.metric_name,
        analysis_run_id=record.analysis_run_id,
        finding_id=record.finding_id,
        case_id=record.case_id,
        router_version=record.router_version,
        feature_extractor_version=record.feature_extractor_version,
        analyzer_registry_version=record.analyzer_registry_version,
        series_profile=record.series_profile or {},
        router_decisions=record.router_decisions or [],
        executed_analyzers=record.executed_analyzers or [],
        generated_findings=record.generated_findings or [],
        outcome_status=record.outcome_status,
        outcome_summary=record.outcome_summary,
        root_cause_category=record.root_cause_category,
        resolution_summary=record.resolution_summary,
        confirmed_analyzers=record.confirmed_analyzers or [],
        rejected_analyzers=record.rejected_analyzers or [],
        resolved_by=record.resolved_by,
        resolved_at=record.resolved_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("/learning-outcomes", response_model=list[AnalyzerLearningOutcomeOut])
def list_learning_outcomes(
    organization_id: str | None = None,
    service_id: str | None = None,
    metric_name: str | None = None,
    analyzer_id: str | None = None,
    outcome_status: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[AnalyzerLearningOutcomeOut]:
    query = select(AnalyzerLearningOutcomeEntity)
    if organization_id:
        query = query.where(AnalyzerLearningOutcomeEntity.organization_id == organization_id)
    if service_id:
        query = query.where(AnalyzerLearningOutcomeEntity.service_id == service_id)
    if metric_name:
        query = query.where(AnalyzerLearningOutcomeEntity.metric_name == metric_name)
    if outcome_status:
        query = query.where(AnalyzerLearningOutcomeEntity.outcome_status == outcome_status)
    if created_from:
        query = query.where(AnalyzerLearningOutcomeEntity.created_at >= created_from)
    if created_to:
        query = query.where(AnalyzerLearningOutcomeEntity.created_at <= created_to)
    query = query.order_by(AnalyzerLearningOutcomeEntity.created_at.desc()).offset(offset).limit(limit)
    records = db.execute(query).scalars().all()
    if analyzer_id:
        records = [
            record for record in records
            if analyzer_id in (record.confirmed_analyzers or []) or analyzer_id in (record.rejected_analyzers or [])
        ]
    return [_to_outcome_out(record) for record in records]


@router.get("/learning-outcomes/{outcome_id}", response_model=AnalyzerLearningOutcomeOut)
def get_learning_outcome(outcome_id: str, db: Session = Depends(get_db)) -> AnalyzerLearningOutcomeOut:
    record = db.execute(
        select(AnalyzerLearningOutcomeEntity).where(AnalyzerLearningOutcomeEntity.id == outcome_id)
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="learning outcome not found")
    return _to_outcome_out(record)


@router.get("/cases/{case_id}/learning-outcomes", response_model=list[AnalyzerLearningOutcomeOut])
def get_case_learning_outcomes(case_id: int, db: Session = Depends(get_db)) -> list[AnalyzerLearningOutcomeOut]:
    records = db.execute(
        select(AnalyzerLearningOutcomeEntity)
        .where(AnalyzerLearningOutcomeEntity.case_id == case_id)
        .order_by(AnalyzerLearningOutcomeEntity.created_at.desc())
    ).scalars().all()
    return [_to_outcome_out(record) for record in records]


@router.post("/cases/{case_id}/learning-outcomes", response_model=AnalyzerLearningOutcomeOut)
def create_case_learning_outcome(
    case_id: int,
    payload: LearningOutcomeCreateRequest,
    db: Session = Depends(get_db),
) -> AnalyzerLearningOutcomeOut:
    try:
        record = AnalyzerLearningService(db).create_from_case_resolution(
            case_id=case_id,
            outcome_status=payload.outcome_status,
            outcome_summary=payload.outcome_summary,
            root_cause_category=payload.root_cause_category,
            resolution_summary=payload.resolution_summary,
            resolved_by=payload.resolved_by,
        )
        db.commit()
        db.refresh(record)
        return _to_outcome_out(record)
    except LearningOutcomeError as exc:
        db.rollback()
        status_code = 409 if "already exists" in str(exc) else 400
        if str(exc) in {"case not found", "analysis run not found"}:
            status_code = 404
        raise HTTPException(status_code=status_code, detail=str(exc))

