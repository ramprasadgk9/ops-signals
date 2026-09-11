from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.memory import get_memory_config, get_memory_indexer
from backend.app.config import MemoryConfig
from backend.app.memory.indexer import CaseMemoryIndexer
from backend.app.models.api_schema import (
    CaseCreateResponse,
    CaseOut,
    InvestigationUpdateRequest,
    RCAUpdateRequest,
    ResolutionUpdateRequest,
)
from backend.app.models.db import get_db
from backend.app.models.entities import FindingEntity, OperationalCaseEntity
from backend.app.services.analyzer_learning_service import AnalyzerLearningService, LearningOutcomeError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cases", tags=["cases"])


def _auto_index_new_case(
    case: OperationalCaseEntity,
    db: Session,
    indexer: CaseMemoryIndexer | None,
    config: MemoryConfig | None,
) -> None:
    """Index a freshly created case into operational memory, if enabled.

    Best-effort: indexing failures must never block case creation. The indexer
    already records the failure on the case (memory_status="failed").
    """
    if not config or not config.enabled or not config.indexing.automatic_on_case_creation or not indexer:
        return
    try:
        indexer.index_case(case, db)
    except Exception as exc:
        logger.warning("Automatic memory indexing failed for case %s: %s", case.id, exc)


def _refresh_case_memory(
    case: OperationalCaseEntity,
    db: Session,
    indexer: CaseMemoryIndexer | None,
    config: MemoryConfig | None,
) -> None:
    """Keep an already-indexed case's memory entry in sync after an update.

    Re-indexes immediately when automatic updates are enabled; otherwise falls
    back to marking the entry stale so a manual re-index can pick it up later.
    """
    if case.memory_status != "indexed":
        return
    if config and config.enabled and config.indexing.automatic_on_case_update and indexer:
        try:
            indexer.index_case(case, db)
            return
        except Exception as exc:
            logger.warning("Automatic memory re-indexing failed for case %s: %s", case.id, exc)
    case.memory_status = "stale"
    db.commit()


def _compute_case_status(case: OperationalCaseEntity) -> tuple[str, str]:
    """
    Compute case_status and investigation_status based on case data.
    
    Rules:
    1. IF investigation notes exist → investigation_status = "in_progress"
    2. IF RCA exists (has summary) AND Resolution exists (has corrective_action) → case_status = "in_progress"
    3. IF RCA verified AND corrective_action exists AND outcome exists → case_status = "resolved" + investigation_status = "completed"
    
    Returns: (case_status, investigation_status)
    """
    investigation_status = case.investigation_status
    case_status = case.case_status
    
    # Rule 1: Investigation has notes
    if case.investigation_notes and len(case.investigation_notes) > 0:
        investigation_status = "in_progress"
    
    # Rule 2: RCA and Resolution both exist
    has_rca = case.root_cause_summary is not None and len(case.root_cause_summary.strip()) > 0
    has_resolution = case.corrective_action is not None and len(case.corrective_action.strip()) > 0
    
    # Rule 3: RCA verified, Resolution exists, Outcome exists
    if (
        case.root_cause_verified
        and has_resolution
        and case.outcome_summary is not None
        and len(case.outcome_summary.strip()) > 0
    ):
        case_status = "resolved"
        investigation_status = "completed"
    # Rule 2 (fallback if rule 3 not met)
    elif has_rca and has_resolution:
        case_status = "in_progress"
    
    return case_status, investigation_status


def _to_case_out(case: OperationalCaseEntity) -> CaseOut:
    # Compute derived statuses
    computed_case_status, computed_investigation_status = _compute_case_status(case)
    
    return CaseOut(
        id=case.id,
        finding_id=case.finding_id,
        analysis_run_id=case.analysis_run_id,
        case_title=case.case_title,
        case_status=computed_case_status,
        finding_snapshot=case.finding_snapshot or {},
        investigation_status=computed_investigation_status,
        investigation_notes=case.investigation_notes or [],
        root_cause_status=case.root_cause_status,
        root_cause_summary=case.root_cause_summary,
        root_cause_confidence=case.root_cause_confidence,
        root_cause_verified=case.root_cause_verified,
        corrective_action=case.corrective_action,
        outcome_status=case.outcome_status,
        outcome_summary=case.outcome_summary,
        memory_status=case.memory_status,
        created_at=case.created_at,
        updated_at=case.updated_at,
        resolved_at=case.resolved_at,
    )


@router.get("", response_model=list[CaseOut])
def list_cases(
    service: str | None = None,
    metric_name: str | None = None,
    limit: int = 25,
    db: Session = Depends(get_db),
) -> list[CaseOut]:
    capped_limit = max(1, min(limit, 200))
    cases = db.execute(
        select(OperationalCaseEntity)
        .order_by(OperationalCaseEntity.updated_at.desc())
        .limit(capped_limit)
    ).scalars().all()
    filtered: list[OperationalCaseEntity] = []
    for case in cases:
        snapshot = case.finding_snapshot or {}
        if service and snapshot.get("service") != service:
            continue
        if metric_name and snapshot.get("metric_name") != metric_name:
            continue
        filtered.append(case)
    return [_to_case_out(case) for case in filtered]


@router.get("/{case_id}", response_model=CaseOut)
def get_case(case_id: int, db: Session = Depends(get_db)) -> CaseOut:
    case = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id == case_id)).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    return _to_case_out(case)


@router.post("/findings/{finding_id}/create", response_model=CaseCreateResponse)
def create_case_from_finding(
    finding_id: int,
    db: Session = Depends(get_db),
    indexer: CaseMemoryIndexer | None = Depends(get_memory_indexer),
    config: MemoryConfig | None = Depends(get_memory_config),
) -> CaseCreateResponse:
    # Load finding
    finding = db.execute(select(FindingEntity).where(FindingEntity.id == finding_id)).scalar_one_or_none()
    if finding is None:
        raise HTTPException(status_code=404, detail="finding not found")
    
    # Check if case already exists for this finding
    existing_case = db.execute(
        select(OperationalCaseEntity).where(OperationalCaseEntity.finding_id == finding_id)
    ).scalar_one_or_none()
    
    if existing_case is not None:
        return CaseCreateResponse(
            case_id=existing_case.id,
            finding_id=finding_id,
            case_status=existing_case.case_status,
            memory_status=existing_case.memory_status,
        )
    
    # Create snapshot of the finding
    finding_snapshot = {
        "id": finding.id,
        "service": finding.service,
        "metric_name": finding.metric_name,
        "title": finding.title,
        "summary": finding.summary,
        "category": finding.category,
        "health_status": finding.health_status,
        "importance_score": finding.importance_score,
        "investigation_priority": finding.investigation_priority,
        "signal_ids": finding.signal_ids,
        "comparison_json": finding.comparison_json or {},
    }
    
    # Create new case
    case = OperationalCaseEntity(
        finding_id=finding_id,
        analysis_run_id=finding.analysis_run_id or "unknown",
        case_title=finding.title,
        case_status="open",
        finding_snapshot=finding_snapshot,
        investigation_status="not_started",
        investigation_notes=[],
        root_cause_status="unknown",
        root_cause_verified=False,
        outcome_status="pending",
        memory_status="not_indexed",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    
    db.add(case)
    db.commit()
    db.refresh(case)

    _auto_index_new_case(case, db, indexer, config)

    return CaseCreateResponse(
        case_id=case.id,
        finding_id=finding_id,
        case_status=case.case_status,
        memory_status=case.memory_status,
    )


@router.patch("/{case_id}/investigation", response_model=CaseOut)
def update_investigation(
    case_id: int,
    payload: InvestigationUpdateRequest,
    db: Session = Depends(get_db),
) -> CaseOut:
    case = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id == case_id)).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    
    case.investigation_status = payload.investigation_status
    
    # Add note if provided
    if payload.investigation_note:
        if case.investigation_notes is None:
            case.investigation_notes = []
        case.investigation_notes.append({
            "timestamp": datetime.utcnow().isoformat(),
            "note": payload.investigation_note,
        })
    
    case.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(case)
    
    return _to_case_out(case)


@router.patch("/{case_id}/rca", response_model=CaseOut)
def update_root_cause_analysis(
    case_id: int,
    payload: RCAUpdateRequest,
    db: Session = Depends(get_db),
    indexer: CaseMemoryIndexer | None = Depends(get_memory_indexer),
    config: MemoryConfig | None = Depends(get_memory_config),
) -> CaseOut:
    case = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id == case_id)).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")

    case.root_cause_status = payload.root_cause_status
    case.root_cause_summary = payload.root_cause_summary
    case.root_cause_confidence = payload.root_cause_confidence
    case.root_cause_verified = payload.root_cause_verified
    case.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(case)

    _refresh_case_memory(case, db, indexer, config)

    return _to_case_out(case)


@router.patch("/{case_id}/resolution", response_model=CaseOut)
def update_resolution(
    case_id: int,
    payload: ResolutionUpdateRequest,
    db: Session = Depends(get_db),
    indexer: CaseMemoryIndexer | None = Depends(get_memory_indexer),
    config: MemoryConfig | None = Depends(get_memory_config),
) -> CaseOut:
    case = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id == case_id)).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    
    final_states = {"resolved", "mitigated", "won_t_fix"}
    if payload.outcome_status in final_states and not payload.learning_outcome_status:
        raise HTTPException(
            status_code=400,
            detail="learning_outcome_status is required when resolving or closing a case",
        )

    case.outcome_status = payload.outcome_status
    case.outcome_summary = payload.outcome_summary
    case.corrective_action = payload.corrective_action
    case.updated_at = datetime.utcnow()

    if payload.outcome_status in final_states and payload.learning_outcome_status:
        try:
            AnalyzerLearningService(db).create_from_case_resolution(
                case_id=case.id,
                outcome_status=payload.learning_outcome_status,
                outcome_summary=payload.outcome_summary,
                root_cause_category=payload.root_cause_category,
                resolution_summary=payload.resolution_summary or payload.outcome_summary,
                resolved_by=payload.resolved_by,
            )
        except LearningOutcomeError as exc:
            db.rollback()
            status_code = 409 if "already exists" in str(exc) else 400
            if str(exc) in {"case not found", "analysis run not found"}:
                status_code = 404
            raise HTTPException(status_code=status_code, detail=str(exc))

    db.commit()
    db.refresh(case)

    _refresh_case_memory(case, db, indexer, config)

    return _to_case_out(case)
