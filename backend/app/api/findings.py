from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.app.ai.services.narrative_service import synthesize_narrative
from backend.app.api.assistant import get_assistant
from backend.app.assistant.service import OperationalIntelligenceAssistant
from backend.app.config import AlertEnrichmentConfig, get_alert_enrichment_config
from backend.app.models.api_schema import FindingAIWordingOut, FindingFeedbackIn, FindingOut
from backend.app.models.db import get_db
from backend.app.models.entities import AnalysisRunEntity, FindingEntity
from backend.app.services.finding_ai_wording import wording_facts, write_ai_wording
from backend.app.services.finding_changes import finding_changes
from backend.app.services.alert_rules import alerts_for_findings
from backend.app.services.finding_plain import finding_plain
from backend.app.services.finding_settings import finding_custom_settings
from backend.app.identity import Actor, actor_name, current_actor
from backend.app.services.finding_trust import finding_trust, record_feedback

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/findings", tags=["findings"])
Window = Literal["1h", "6h", "24h", "7d"]
FindingSource = Literal["prometheus", "otlp", "csv"]
# analysis_runs.source_type -> the source a finding reports; the OTLP cycle writes "otel".
_RUN_SOURCE_TYPES: dict[FindingSource, str] = {"prometheus": "prometheus", "otlp": "otel", "csv": "csv"}
_FINDING_SOURCES = {source_type: source for source, source_type in _RUN_SOURCE_TYPES.items()}


def _window_start(window: Window) -> datetime:
    now = datetime.now(timezone.utc)
    if window == "1h":
        return now - timedelta(hours=1)
    if window == "6h":
        return now - timedelta(hours=6)
    if window == "7d":
        return now - timedelta(days=7)
    return now - timedelta(hours=24)


def _to_finding_out(
    finding: FindingEntity,
    changes: dict | None = None,
    connection_id: str | None = None,
    trust: dict | None = None,
    source: str | None = None,
    plain: dict | None = None,
    custom_settings: dict | None = None,
) -> FindingOut:
    return FindingOut(
        id=finding.id,
        service=finding.service,
        metric_name=finding.metric_name,
        cluster=finding.cluster,
        connection_id=connection_id,
        source=source,
        title=finding.title,
        summary=finding.summary,
        ai_summary=finding.ai_summary,
        category=finding.category,
        health_status=finding.health_status,
        importance_score=finding.importance_score,
        investigation_priority=finding.investigation_priority,
        signal_ids=finding.signal_ids,
        comparison_json=finding.comparison_json or {},
        analysis_run_id=finding.analysis_run_id,
        created_at=finding.created_at,
        event_start=finding.event_start,
        event_end=finding.event_end,
        ongoing=finding.ongoing,
        problem_id=finding.problem_id,
        changes=changes,
        trust=trust,
        plain=plain,
        custom_settings=custom_settings,
    )


def _with_changes(db: Session, rows: list[FindingEntity], config: AlertEnrichmentConfig) -> list[FindingOut]:
    changes = finding_changes(db, rows, config)
    run_ids = {row.analysis_run_id for row in rows if row.analysis_run_id}
    runs = (
        {
            run_id: (connection_id, source_type)
            for run_id, connection_id, source_type in db.execute(
                select(AnalysisRunEntity.id, AnalysisRunEntity.connection_id, AnalysisRunEntity.source_type).where(AnalysisRunEntity.id.in_(run_ids))
            ).all()
        }
        if run_ids
        else {}
    )
    trust = finding_trust(db, rows)
    # What the team's Prometheus alerts say about each finding's metric; none when they can't be read.
    plain = finding_plain(db, rows, alerts=alerts_for_findings(db, rows, config.service_labels), service_labels=config.service_labels)
    custom = finding_custom_settings(db, rows)
    out = []
    for row in rows:
        connection_id, source_type = runs.get(row.analysis_run_id, (None, None))
        row_trust = trust.get(row.id)
        if row.id in custom and row_trust is not None:
            # The tested numbers were measured with the default settings; they don't describe
            # a finding made with settings a team chose.
            row_trust = {**row_trust, "tested": None, "custom_settings": True}
        out.append(
            _to_finding_out(
                row, changes.get(row.id), connection_id, row_trust, _FINDING_SOURCES.get(source_type or "", source_type), plain.get(row.id), custom.get(row.id)
            )
        )
    return out


def _from_source(query, source: FindingSource | None):
    if not source:
        return query
    runs = select(AnalysisRunEntity.id).where(AnalysisRunEntity.source_type == _RUN_SOURCE_TYPES[source])
    return query.where(FindingEntity.analysis_run_id.in_(runs))


def _ensure_ai_summary(finding: FindingEntity, db: Session, assistant: OperationalIntelligenceAssistant | None) -> None:
    """Best-effort, cached AI polish of a finding's summary - computed once, on first detail-page
    fetch, and never touching the existing `summary` field. A missing AI service, a failed call,
    or any unexpected error here must never prevent the finding from being returned; it just means
    `ai_summary` stays None and callers keep using `summary` exactly as they always have."""
    if finding.ai_summary or not assistant or not assistant.services.ai_services:
        return
    evidence_text = (
        f"Title: {finding.title}\n"
        f"Category: {finding.category}\n"
        f"Health status: {finding.health_status}\n"
        f"Service: {finding.service or 'unknown'}\n"
        f"Metric: {finding.metric_name}\n"
        f"Summary: {finding.summary}\n"
        f"Comparison data: {finding.comparison_json or {}}"
    )
    try:
        polished = synthesize_narrative(
            assistant.services.ai_services,
            instruction=(
                "Rewrite this operational finding's summary as 1-2 clear, plain-language sentences for an "
                "on-call engineer, using ONLY the evidence given - do not invent numbers, causes, or facts "
                "not present in the evidence."
            ),
            evidence_text=evidence_text,
            max_tokens=120,
        )
    except Exception:
        return
    if not polished:
        return
    finding.ai_summary = polished
    db.commit()


@router.get("", response_model=list[FindingOut])
def list_findings(
    service: str | None = None,
    metric_name: str | None = None,
    cluster: str | None = None,
    health_status: str | None = None,
    category: str | None = None,
    analysis_run_id: str | None = Query(default=None),
    window: Window | None = Query(default=None),
    source: FindingSource | None = Query(default=None, description="Where the finding's data came from."),
    db: Session = Depends(get_db),
    config: AlertEnrichmentConfig = Depends(get_alert_enrichment_config),
) -> list[FindingOut]:
    query = select(FindingEntity)
    if service:
        query = query.where(FindingEntity.service == service)
    if metric_name:
        query = query.where(FindingEntity.metric_name == metric_name)
    if cluster:
        query = query.where(FindingEntity.cluster == cluster)
    if health_status:
        query = query.where(FindingEntity.health_status == health_status)
    if category:
        query = query.where(FindingEntity.category == category)
    if analysis_run_id:
        query = query.where(FindingEntity.analysis_run_id == analysis_run_id)
    if window:
        query = query.where(FindingEntity.created_at >= _window_start(window))
    query = _from_source(query, source)
    rows = db.execute(query.order_by(FindingEntity.importance_score.desc())).scalars().all()
    return _with_changes(db, list(rows), config)


@router.get("/search", response_model=list[FindingOut])
def search_findings(
    q: str | None = Query(default=None, description="Optional text search across title, summary, service, metric, and category."),
    service: str | None = None,
    metric_name: str | None = None,
    cluster: str | None = None,
    health_status: str | None = None,
    category: str | None = None,
    analysis_run_id: str | None = Query(default=None),
    window: Window = Query(default="24h"),
    limit: int = Query(default=25, ge=1, le=200),
    source: FindingSource | None = Query(default=None, description="Where the finding's data came from."),
    db: Session = Depends(get_db),
    config: AlertEnrichmentConfig = Depends(get_alert_enrichment_config),
) -> list[FindingOut]:
    query = select(FindingEntity).where(FindingEntity.created_at >= _window_start(window))
    if service:
        query = query.where(FindingEntity.service == service)
    if metric_name:
        query = query.where(FindingEntity.metric_name == metric_name)
    if cluster:
        query = query.where(FindingEntity.cluster == cluster)
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
    query = _from_source(query, source)
    rows = db.execute(query.order_by(FindingEntity.importance_score.desc(), FindingEntity.created_at.desc()).limit(limit)).scalars().all()
    return _with_changes(db, list(rows), config)


@router.get("/{finding_id}", response_model=FindingOut)
def get_finding(
    finding_id: int,
    db: Session = Depends(get_db),
    assistant: OperationalIntelligenceAssistant | None = Depends(get_assistant),
    config: AlertEnrichmentConfig = Depends(get_alert_enrichment_config),
) -> FindingOut:
    row = db.execute(select(FindingEntity).where(FindingEntity.id == finding_id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="finding not found")
    out = _with_changes(db, [row], config)[0]
    # A finding with plain wording shows that instead of its summary, and gets AI wording from
    # GET /ai-wording; polishing a summary nobody sees would only make this request wait.
    if out.plain is None:
        _ensure_ai_summary(row, db, assistant)
        out.ai_summary = row.ai_summary
    return out


@router.get("/{finding_id}/ai-wording", response_model=FindingAIWordingOut)
def get_finding_ai_wording(
    finding_id: int,
    db: Session = Depends(get_db),
    assistant: OperationalIntelligenceAssistant | None = Depends(get_assistant),
) -> FindingAIWordingOut:
    """Why it matters, an extra thing to check and an extra Happened with sentence, written by the
    AI provider for this finding on its first open and saved. Asked for after the details page
    shows, so the page never waits for the model; every line that is None keeps the template."""
    row = db.execute(select(FindingEntity).where(FindingEntity.id == finding_id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="finding not found")
    if row.ai_wording:
        return FindingAIWordingOut(available=True, **_wording_lines(row.ai_wording))
    ai_services = assistant.services.ai_services if assistant else None
    plain = finding_plain(db, [row]).get(row.id)
    if plain is None:
        return FindingAIWordingOut(available=False, reason="no_plain")
    if ai_services is None:
        return FindingAIWordingOut(available=False, reason="ai_off")
    try:
        written = write_ai_wording(ai_services, wording_facts(row.metric_name, row.service, plain))
    except Exception:  # noqa: BLE001 - AI wording must never break the details page
        logger.warning("AI wording failed for finding %s", finding_id, exc_info=True)
        written = None
    if written is None:
        return FindingAIWordingOut(available=False, reason="failed")
    row.ai_wording = written
    try:
        db.commit()
    except Exception:  # noqa: BLE001 - still show what was written; the next open writes it again
        db.rollback()
        logger.warning("Could not save AI wording for finding %s", finding_id, exc_info=True)
    return FindingAIWordingOut(available=True, **_wording_lines(written))


def _wording_lines(saved: dict) -> dict:
    return {key: saved.get(key) for key in ("why", "check_extra", "related_extra", "model")}


@router.post("/{finding_id}/feedback", response_model=FindingOut)
def finding_feedback(
    finding_id: int,
    payload: FindingFeedbackIn,
    db: Session = Depends(get_db),
    config: AlertEnrichmentConfig = Depends(get_alert_enrichment_config),
    actor: Actor | None = Depends(current_actor),
) -> FindingOut:
    """The team's answer to "Was this real?". Answering again changes the answer. Returns the
    finding with its trust recomputed, so the card shows the new service count at once."""
    row = db.execute(select(FindingEntity).where(FindingEntity.id == finding_id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="finding not found")
    record_feedback(db, row, payload.verdict, answered_by=actor_name(actor))
    return _with_changes(db, [row], config)[0]
