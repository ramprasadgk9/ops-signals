from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.alerts.correlation import as_utc
from backend.app.identity import Actor, actor_name, current_actor
from backend.app.ai.services.narrative_service import synthesize_narrative
from backend.app.api.assistant import get_assistant
from backend.app.api.memory import get_memory_config, get_memory_indexer, get_similarity_service
from backend.app.api.ticketing import get_ticketing_service
from backend.app.assistant.service import OperationalIntelligenceAssistant
from backend.app.config import AlertEnrichmentConfig, MemoryConfig, get_alert_enrichment_config
from backend.app.integrations.ticketing.service import CaseTicketing
from backend.app.memory.indexer import CaseMemoryIndexer
from backend.app.memory.similarity_service import SimilarityService
from backend.app.models.api_schema import (
    CaseCreateResponse,
    CaseOut,
    CaseTimelineOut,
    InvestigationUpdateRequest,
    RCADraftOut,
    RCAUpdateRequest,
    ResolutionDraftOut,
    ResolutionUpdateRequest,
    WriteupDraftOut,
    WriteupUpdateRequest,
)
from backend.app.models.db import get_db
from backend.app.models.entities import AnalysisRunEntity, BehaviorFindingEntity, FindingEntity, OperationalCaseEntity
from backend.app.services.analyzer_learning_service import AnalyzerLearningService, LearningOutcomeError
from backend.app.services.case_ai_drafts import RCA_INSTRUCTION, check_draft, rca_facts, resolution_facts, write_resolution, write_writeup, writeup_facts
from backend.app.services.case_timeline import case_timeline
from backend.app.memory.document_builder import CaseDocumentBuilder
from backend.app.services.case_status import CLOSING_OUTCOMES, derive_case_status, sync_case_status

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


def _note_out(note: dict) -> dict:
    """The note with its time marked as UTC. Notes saved before this was fixed hold UTC times with no
    zone (`2026-10-30T17:13:06`), which browsers read as local time, so the note showed hours off."""
    stamp = note.get("timestamp")
    if not isinstance(stamp, str):
        return note
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return note
    return {**note, "timestamp": as_utc(moment).isoformat()}


def _to_case_out(case: OperationalCaseEntity) -> CaseOut:
    computed_case_status, computed_investigation_status = derive_case_status(case)
    
    return CaseOut(
        id=case.id,
        finding_id=case.finding_id,
        behavior_finding_id=case.behavior_finding_id,
        analysis_run_id=case.analysis_run_id,
        case_title=case.case_title,
        case_status=computed_case_status,
        finding_snapshot=case.finding_snapshot or {},
        investigation_status=computed_investigation_status,
        investigation_notes=[_note_out(note) for note in case.investigation_notes or []],
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
        source=case.source or "detected",
        source_id=case.source_id,
        source_url=case.source_url,
        import_batch_id=case.import_batch_id,
        created_by=case.created_by,
        resolved_by=case.resolved_by,
        writeup=case.writeup,
    )


@router.get("", response_model=list[CaseOut])
def list_cases(
    service: str | None = None,
    metric_name: str | None = None,
    limit: int = 25,
    db: Session = Depends(get_db),
) -> list[CaseOut]:
    capped_limit = max(1, min(limit, 200))
    # Filter in SQL, before the limit: filtering the newest N afterwards dropped a service's
    # older cases whenever other services had N newer ones.
    query = select(OperationalCaseEntity)
    if service:
        query = query.where(OperationalCaseEntity.finding_snapshot["service"].as_string() == service)
    if metric_name:
        query = query.where(OperationalCaseEntity.finding_snapshot["metric_name"].as_string() == metric_name)
    cases = db.execute(
        query.order_by(OperationalCaseEntity.updated_at.desc()).limit(capped_limit)
    ).scalars().all()
    return [_to_case_out(case) for case in cases]


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
    actor: Actor | None = Depends(current_actor),
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
    
    # Create snapshot of the finding. Cluster and connection say where its data came from when one
    # Mimir or Thanos holds several clusters or tenants; None for single-cluster data.
    connection_id = (
        db.execute(select(AnalysisRunEntity.connection_id).where(AnalysisRunEntity.id == finding.analysis_run_id)).scalar_one_or_none()
        if finding.analysis_run_id
        else None
    )
    finding_snapshot = {
        "id": finding.id,
        "service": finding.service,
        "metric_name": finding.metric_name,
        "cluster": finding.cluster,
        "connection_id": connection_id,
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
        created_by=actor_name(actor),
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
    try:
        db.commit()
    except IntegrityError:
        # Someone else opened a case for this finding between the check above and this insert.
        existing_case = _case_created_concurrently(db, OperationalCaseEntity.finding_id == finding_id)
        return CaseCreateResponse(
            case_id=existing_case.id,
            finding_id=finding_id,
            case_status=existing_case.case_status,
            memory_status=existing_case.memory_status,
        )
    db.refresh(case)

    _auto_index_new_case(case, db, indexer, config)

    return CaseCreateResponse(
        case_id=case.id,
        finding_id=finding_id,
        case_status=case.case_status,
        memory_status=case.memory_status,
    )


def _case_created_concurrently(db: Session, link) -> OperationalCaseEntity:
    """The case a concurrent request inserted first; the unique index rejected ours. Any other
    integrity error has no such case and is raised as before."""
    db.rollback()
    existing_case = db.execute(select(OperationalCaseEntity).where(link)).scalar_one_or_none()
    if existing_case is None:
        raise
    return existing_case


def _behavior_snapshot(behavior: BehaviorFindingEntity) -> dict:
    """Normalizes a BehaviorFinding into the same snapshot shape a single-metric Finding
    uses (service/metric_name/category/health_status/importance_score/summary), so every
    downstream reader of finding_snapshot (case listing filters, similarity-search filters,
    the case document builder, learning-outcome creation) keeps working unchanged for
    behavior-sourced cases. A behavior spans multiple input metrics; metric_name here is
    the first one, with the full set kept under metric_names for anything that wants it."""
    input_metrics = list((behavior.input_metrics_json or {}).values())
    return {
        "id": behavior.id,
        "source_type": "behavior",
        "service": behavior.service,
        "metric_name": input_metrics[0] if input_metrics else None,
        "metric_names": input_metrics,
        "title": behavior.title,
        "summary": behavior.summary,
        "category": behavior.category,
        "health_status": behavior.severity,
        "importance_score": behavior.confidence,
        "evidence_facts": behavior.evidence_json or [],
        "matched_conditions": behavior.matched_conditions_json or [],
    }


@router.post("/behaviors/{behavior_finding_id}/create", response_model=CaseCreateResponse)
def create_case_from_behavior(
    behavior_finding_id: int,
    db: Session = Depends(get_db),
    indexer: CaseMemoryIndexer | None = Depends(get_memory_indexer),
    config: MemoryConfig | None = Depends(get_memory_config),
    actor: Actor | None = Depends(current_actor),
) -> CaseCreateResponse:
    """Same lifecycle as create_case_from_finding, but for a correlated, cross-metric
    BehaviorFinding (e.g. "memory leak driving resource exhaustion") instead of a
    single-metric Finding. Without this, behaviors - the closer-to-root-cause output of
    the Behavior Intelligence Engine - could never get an RCA, resolution, or outcome
    recorded, and so could never inform learning outcomes or similar-case search."""
    behavior = db.execute(
        select(BehaviorFindingEntity).where(BehaviorFindingEntity.id == behavior_finding_id)
    ).scalar_one_or_none()
    if behavior is None:
        raise HTTPException(status_code=404, detail="behavior finding not found")

    existing_case = db.execute(
        select(OperationalCaseEntity).where(OperationalCaseEntity.behavior_finding_id == behavior_finding_id)
    ).scalar_one_or_none()

    if existing_case is not None:
        return CaseCreateResponse(
            case_id=existing_case.id,
            behavior_finding_id=behavior_finding_id,
            case_status=existing_case.case_status,
            memory_status=existing_case.memory_status,
        )

    case = OperationalCaseEntity(
        created_by=actor_name(actor),
        finding_id=None,
        behavior_finding_id=behavior_finding_id,
        analysis_run_id=behavior.analysis_run_id or "unknown",
        case_title=behavior.title,
        case_status="open",
        finding_snapshot=_behavior_snapshot(behavior),
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
    try:
        db.commit()
    except IntegrityError:
        existing_case = _case_created_concurrently(db, OperationalCaseEntity.behavior_finding_id == behavior_finding_id)
        return CaseCreateResponse(
            case_id=existing_case.id,
            behavior_finding_id=behavior_finding_id,
            case_status=existing_case.case_status,
            memory_status=existing_case.memory_status,
        )
    db.refresh(case)

    behavior.case_id = case.id
    db.commit()

    _auto_index_new_case(case, db, indexer, config)

    return CaseCreateResponse(
        case_id=case.id,
        behavior_finding_id=behavior_finding_id,
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
    
    # Add note if provided (reassign list so SQLAlchemy tracks JSON mutation)
    if payload.investigation_note:
        notes = list(case.investigation_notes or [])
        notes.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "note": payload.investigation_note,
        })
        case.investigation_notes = notes
    
    sync_case_status(case)
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
    sync_case_status(case)
    case.updated_at = datetime.utcnow()

    # Outbound resolution sync: when RCA is approved/verified AND case is resolved/mitigated
    if payload.root_cause_verified and case.outcome_status in {"resolved", "mitigated"}:
        try:
            ticketing_svc = get_ticketing_service()
            ticketing_svc.request_resolve(case_id=case.id, session=db)
        except Exception as ticketing_exc:
            logger.warning("Optional ticket resolution sync failed to enqueue for case %s: %s", case.id, ticketing_exc)

    db.commit()
    db.refresh(case)

    _refresh_case_memory(case, db, indexer, config)

    return _to_case_out(case)


_AI_OFF = "AI assistance is not configured"
_FAILED = "AI draft generation failed"


@router.post("/{case_id}/rca/suggest", response_model=RCADraftOut)
def suggest_root_cause_analysis(
    case_id: int,
    db: Session = Depends(get_db),
    assistant: OperationalIntelligenceAssistant | None = Depends(get_assistant),
    similarity_service: SimilarityService | None = Depends(get_similarity_service),
    ticketing_service: CaseTicketing | None = Depends(get_ticketing_service),
    change_config: AlertEnrichmentConfig = Depends(get_alert_enrichment_config),
) -> RCADraftOut:
    """Draft-only RCA hypothesis written up from what the case holds (case_ai_drafts.py). Never
    writes anything - PATCH /rca is still the only way to actually save an RCA. Returns
    available=False (not a fabricated draft) whenever AI is off, nobody has recorded anything to
    draft from, or a call fails."""
    case = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id == case_id)).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    if not assistant or not assistant.services.ai_services:
        return RCADraftOut(available=False, reason=_AI_OFF, reason_code="ai_off")

    facts = rca_facts(case, db, ticketing=ticketing_service, similarity=similarity_service, change_config=change_config)
    if not facts.has_material:
        return RCADraftOut(
            available=False,
            reason="Nothing on this case to draft from yet: no notes, ticket comments, matched deploy or similar past case",
            reason_code="not_enough",
            sources=facts.sources,
        )
    try:
        draft = synthesize_narrative(assistant.services.ai_services, instruction=RCA_INSTRUCTION, evidence_text=facts.text, max_tokens=200)
    except Exception:
        draft = None
    draft = check_draft(draft, facts.text)
    if not draft:
        return RCADraftOut(available=False, reason=_FAILED, reason_code="failed")
    return RCADraftOut(available=True, draft=draft, based_on_similar_cases=facts.similar_case_ids, sources=facts.sources)


@router.post("/{case_id}/resolution/suggest", response_model=ResolutionDraftOut)
def suggest_resolution_summary(
    case_id: int,
    db: Session = Depends(get_db),
    assistant: OperationalIntelligenceAssistant | None = Depends(get_assistant),
    ticketing_service: CaseTicketing | None = Depends(get_ticketing_service),
) -> ResolutionDraftOut:
    """Draft-only outcome summary and corrective action from the case's own notes, ticket comments
    and saved root cause. Never writes anything - PATCH /resolution is still the only way to
    actually save an outcome. Returns available=False (not a fabricated draft) whenever AI is off,
    there is no material to draft from, or a call fails."""
    case = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id == case_id)).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    if not assistant or not assistant.services.ai_services:
        return ResolutionDraftOut(available=False, reason=_AI_OFF, reason_code="ai_off")

    facts = resolution_facts(case, db, ticketing=ticketing_service)
    if not facts.has_material:
        return ResolutionDraftOut(available=False, reason="No investigation notes, root cause, or corrective action recorded yet", reason_code="not_enough")
    try:
        draft = write_resolution(assistant.services.ai_services, facts)
    except Exception:
        draft = None
    if not draft or not (draft["outcome_summary"] or draft["corrective_action"]):
        return ResolutionDraftOut(available=False, reason=_FAILED, reason_code="failed")
    return ResolutionDraftOut(available=True, draft=draft["outcome_summary"], corrective_action=draft["corrective_action"], sources=facts.sources)


@router.get("/{case_id}/timeline", response_model=CaseTimelineOut)
def get_case_timeline(
    case_id: int,
    db: Session = Depends(get_db),
    change_config: AlertEnrichmentConfig = Depends(get_alert_enrichment_config),
) -> CaseTimelineOut:
    """Publish Knowledge: what happened, in order, built from the case (no AI), and the text memory
    indexes for it."""
    case = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id == case_id)).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    timeline = case_timeline(case, db, change_config)
    return CaseTimelineOut(**timeline, memory_text=CaseDocumentBuilder.build(case))


@router.patch("/{case_id}/writeup", response_model=CaseOut)
def update_writeup(
    case_id: int,
    payload: WriteupUpdateRequest,
    db: Session = Depends(get_db),
    indexer: CaseMemoryIndexer | None = Depends(get_memory_indexer),
    config: MemoryConfig | None = Depends(get_memory_config),
) -> CaseOut:
    case = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id == case_id)).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    case.writeup = (payload.writeup or "").strip() or None
    case.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(case)
    _refresh_case_memory(case, db, indexer, config)
    return _to_case_out(case)


@router.post("/{case_id}/writeup/suggest", response_model=WriteupDraftOut)
def suggest_writeup(
    case_id: int,
    db: Session = Depends(get_db),
    assistant: OperationalIntelligenceAssistant | None = Depends(get_assistant),
    similarity_service: SimilarityService | None = Depends(get_similarity_service),
    change_config: AlertEnrichmentConfig = Depends(get_alert_enrichment_config),
) -> WriteupDraftOut:
    """Draft-only write-up from the saved root cause and resolution, the timeline and similar past
    cases. Never writes anything - PATCH /writeup saves."""
    case = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id == case_id)).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    if not assistant or not assistant.services.ai_services:
        return WriteupDraftOut(available=False, reason=_AI_OFF, reason_code="ai_off")

    facts = writeup_facts(case, db, timeline=case_timeline(case, db, change_config), similarity=similarity_service)
    if not facts.has_material:
        return WriteupDraftOut(available=False, reason="Save a root cause or a resolution first", reason_code="not_enough")
    try:
        draft = write_writeup(assistant.services.ai_services, facts)
    except Exception:
        draft = None
    if not draft:
        return WriteupDraftOut(available=False, reason=_FAILED, reason_code="failed")
    return WriteupDraftOut(available=True, draft=draft, sources=facts.sources)


@router.patch("/{case_id}/resolution", response_model=CaseOut)
def update_resolution(
    case_id: int,
    payload: ResolutionUpdateRequest,
    db: Session = Depends(get_db),
    indexer: CaseMemoryIndexer | None = Depends(get_memory_indexer),
    config: MemoryConfig | None = Depends(get_memory_config),
    actor: Actor | None = Depends(current_actor),
) -> CaseOut:
    case = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id == case_id)).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    
    final_states = CLOSING_OUTCOMES
    # Learning outcomes score the analyzers behind a detection; an imported case has none.
    learns = not case.is_imported
    if learns and payload.outcome_status in final_states and not payload.learning_outcome_status:
        raise HTTPException(
            status_code=400,
            detail="learning_outcome_status is required when resolving or closing a case",
        )

    # Who closed it: set when it moves into a closing outcome, kept while it stays closed, cleared
    # when it is reopened.
    was_closed = case.outcome_status in final_states
    if payload.outcome_status in final_states and not was_closed:
        case.resolved_by = actor_name(actor)
    elif payload.outcome_status not in final_states:
        case.resolved_by = None
    case.outcome_status = payload.outcome_status
    case.outcome_summary = payload.outcome_summary
    case.corrective_action = payload.corrective_action
    sync_case_status(case)
    case.updated_at = datetime.utcnow()

    if learns and payload.outcome_status in final_states and payload.learning_outcome_status:
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

    # Outbound resolution sync: when case is resolved/mitigated AND RCA is approved/verified
    if case.root_cause_verified and payload.outcome_status in {"resolved", "mitigated"}:
        try:
            ticketing_svc = get_ticketing_service()
            ticketing_svc.request_resolve(case_id=case.id, session=db)
        except Exception as ticketing_exc:
            logger.warning("Optional ticket resolution sync failed to enqueue for case %s: %s", case.id, ticketing_exc)

    db.commit()
    db.refresh(case)

    _refresh_case_memory(case, db, indexer, config)

    return _to_case_out(case)
