"""Start, continue and stop guided investigations; mark their steps; attach them to a case.

A round runs in a background thread (run_round), so the request that starts it returns at once and
the dialog polls GET /api/investigations/{id}. Only one round of an investigation runs at a time.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ai.factory import build_llm_client, llm_client_issue
from backend.app.ai.interfaces import LLMClient
from backend.app.ai.providers.noop import NoOpLLMClient
from backend.app.ai.tool_calls import ToolTurn, turn_to_dict
from backend.app.config import AlertEnrichmentConfig, get_prometheus_connections
from backend.app.investigation import loop
from backend.app.investigation.context import SOURCES, FindingContext, change_lines, finding_context, first_message
from backend.app.investigation.tools import ToolBox
from backend.app.models.db import get_session_local
from backend.app.models.entities import (
    FindingEntity,
    InvestigationCheckEntity,
    InvestigationEntity,
    InvestigationStepEntity,
    OperationalCaseEntity,
)
from backend.app.services import service_notes
from backend.app.services.case_status import sync_case_status
from backend.app.services.prometheus_service import PrometheusQueryService

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="investigation")


def submit(task: Callable[[], None]) -> None:
    """Run a round in the background. Tests replace this to run it in place."""
    _executor.submit(task)


def ai_client() -> LLMClient | None:
    """The AI client the assistant uses, or one built from the AI settings; None when AI is off."""
    from backend.app.api import ai as ai_api

    client = ai_api._active_client()
    if client is not None:
        return client
    config = ai_api._services.get("config")
    if config is None or not config.enabled or llm_client_issue(config):
        return None
    built = build_llm_client(config)
    return None if isinstance(built, NoOpLLMClient) else built


def start_info(db: Session, finding_id: int, client: LLMClient | None) -> dict[str, Any]:
    """What the Investigate dialog shows before Start."""
    finding = _finding(db, finding_id)
    context = finding_context(db, finding)
    latest = db.execute(
        select(InvestigationEntity).where(InvestigationEntity.finding_id == finding_id).order_by(InvestigationEntity.id.desc())
    ).scalars().first()
    return {
        "finding_id": finding_id,
        "eligible": context.eligible,
        "reason": context.reason,
        "ai_on": client is not None,
        "service": context.service,
        "connection_id": context.connection_id,
        "connection_name": context.connection_name,
        "has_query": bool(context.promql),
        "note": context.note,
        "latest": summary_dict(latest) if latest else None,
    }


def start(
    db: Session,
    finding_id: int,
    *,
    client: LLMClient | None,
    config: AlertEnrichmentConfig,
    note: str | None,
    save_note: bool,
    skipped: list[str],
    by: str | None,
) -> dict[str, Any]:
    if client is None:
        raise HTTPException(status_code=400, detail="AI is off. Investigate needs an AI provider; see AI settings.")
    finding = _finding(db, finding_id)
    context = finding_context(db, finding)
    if not context.eligible:
        raise HTTPException(status_code=400, detail=context.reason)
    running = db.execute(
        select(InvestigationEntity).where(InvestigationEntity.finding_id == finding_id, InvestigationEntity.status == "running")
    ).scalars().first()
    if running is not None:
        return investigation_dict(db, running)

    skipped = [source for source in skipped if source in SOURCES]
    note = (note or "").strip()[:1000] or None
    if note and save_note and context.service:
        service_notes.add_behaviour(db, context.service, note, by)
        context = finding_context(db, finding)
    changes = change_lines(db, context, config) if "changes" not in skipped else []
    opening = ToolTurn(role="user", content=first_message(context, changes, note, skipped))
    investigation = InvestigationEntity(
        finding_id=finding_id,
        service=context.service,
        status="running",
        context_note=note,
        skipped_sources=skipped,
        transcript=[turn_to_dict(opening)],
        round=1,
        check_budget=loop.FIRST_BUDGET,
        started_by=by,
    )
    db.add(investigation)
    db.commit()
    _run_in_background(investigation.id, client, config)
    return investigation_dict(db, investigation)


def continue_investigation(db: Session, investigation_id: int, *, client: LLMClient | None, config: AlertEnrichmentConfig, message: str | None) -> dict[str, Any]:
    """Another round: everything the person marked or noted so far, plus what they just said."""
    if client is None:
        raise HTTPException(status_code=400, detail="AI is off. Investigate needs an AI provider; see AI settings.")
    investigation = _investigation(db, investigation_id)
    if investigation.status == "running":
        raise HTTPException(status_code=409, detail="This investigation is still running.")
    text = input_message(db, investigation, message)
    turns = [*investigation.transcript, turn_to_dict(ToolTurn(role="user", content=text))]
    investigation.transcript = turns
    investigation.round += 1
    investigation.check_budget = loop.LATER_BUDGET
    investigation.checks_used = 0
    investigation.status = "running"
    investigation.ending = None
    investigation.ending_detail = None
    investigation.question = None
    investigation.stop_requested = False
    investigation.updated_at = datetime.now(timezone.utc)
    db.commit()
    _run_in_background(investigation.id, client, config)
    return investigation_dict(db, investigation)


def input_message(db: Session, investigation: InvestigationEntity, message: str | None) -> str:
    steps = _steps(db, investigation.id)
    marks = []
    for step in steps:
        if not step.mark and not step.note:
            continue
        said = {"found": "found something", "ruled_out": "ruled it out"}.get(step.mark or "", "added a note")
        marks.append(f'- Step "{step.title}": {said}.' + (f' Note: "{step.note}"' if step.note else ""))
    parts = ["The engineer's input so far:", *marks] if marks else []
    if message and message.strip():
        parts.append(f'The engineer says: "{message.strip()[:1000]}"')
    if not parts:
        parts.append("The engineer asks you to keep going.")
    parts.append("Check further where it helps, then reply with only the new steps.")
    return "\n".join(parts)


def stop(db: Session, investigation_id: int) -> dict[str, Any]:
    investigation = _investigation(db, investigation_id)
    if investigation.status == "running":
        investigation.stop_requested = True
        db.commit()
    return investigation_dict(db, investigation)


def mark_step(db: Session, investigation_id: int, step_id: int, *, mark: str | None, note: str | None, by: str | None) -> dict[str, Any]:
    step = db.get(InvestigationStepEntity, step_id)
    if step is None or step.investigation_id != investigation_id:
        raise HTTPException(status_code=404, detail="step not found")
    if mark not in {None, "found", "ruled_out"}:
        raise HTTPException(status_code=422, detail="mark must be found, ruled_out or null")
    step.mark = mark
    step.note = (note or "").strip()[:1000] or None
    step.marked_by = by
    db.commit()
    return investigation_dict(db, _investigation(db, investigation_id))


def attach_to_case(db: Session, investigation_id: int, case_id: int, by: str | None) -> dict[str, Any]:
    """Link the investigation to its case and add what it found as an investigation note, so the
    case's "Draft from case" can use it. Only steps a person marked count as found."""
    investigation = _investigation(db, investigation_id)
    case = db.get(OperationalCaseEntity, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    investigation.case_id = case_id
    steps = _steps(db, investigation_id)
    found = [step for step in steps if step.mark == "found"]
    ruled_out = [step for step in steps if step.mark == "ruled_out" or (step.status == "ruled_out" and step.kind == "checked" and not step.unverified)]
    lines = [f"Guided investigation #{investigation.id}" + (f" by {by}" if by else "") + "."]
    if investigation.summary:
        lines.append(f"Where to look (suggested, not confirmed): {investigation.summary}")
    lines += [f"Found something: {step.title}." + (f" {step.result}" if step.result else "") + (f' Note: "{step.note}"' if step.note else "") for step in found]
    if ruled_out:
        lines.append("Ruled out: " + "; ".join(step.title for step in ruled_out) + ".")
    notes = [step for step in steps if step.note and step.mark != "found"]
    lines += [f'Note on "{step.title}": "{step.note}"' for step in notes]
    case.investigation_notes = [
        *(case.investigation_notes or []),
        {"timestamp": datetime.now(timezone.utc).isoformat(), "note": "\n".join(lines), "investigation_id": investigation.id},
    ]
    if case.investigation_status == "not_started":
        case.investigation_status = "in_progress"
    sync_case_status(case)
    case.updated_at = datetime.utcnow()
    db.commit()
    return investigation_dict(db, investigation)


def list_for(db: Session, *, finding_id: int | None, case_id: int | None) -> list[dict[str, Any]]:
    query = select(InvestigationEntity).order_by(InvestigationEntity.id.desc()).limit(20)
    if finding_id is not None:
        query = query.where(InvestigationEntity.finding_id == finding_id)
    if case_id is not None:
        query = query.where(InvestigationEntity.case_id == case_id)
    return [summary_dict(row) for row in db.execute(query).scalars()]


def get(db: Session, investigation_id: int) -> dict[str, Any]:
    return investigation_dict(db, _investigation(db, investigation_id))


def summary_dict(investigation: InvestigationEntity) -> dict[str, Any]:
    return {
        "id": investigation.id,
        "finding_id": investigation.finding_id,
        "service": investigation.service,
        "status": investigation.status,
        "ending": investigation.ending,
        "ending_detail": investigation.ending_detail,
        "summary": investigation.summary,
        "question": investigation.question,
        "round": investigation.round,
        "checks_used": investigation.checks_used,
        "check_budget": investigation.check_budget,
        "case_id": investigation.case_id,
        "model": investigation.model,
        "started_by": investigation.started_by,
        "context_note": investigation.context_note,
        "skipped_sources": list(investigation.skipped_sources or []),
        "created_at": _iso(investigation.created_at),
        "updated_at": _iso(investigation.updated_at),
    }


def investigation_dict(db: Session, investigation: InvestigationEntity) -> dict[str, Any]:
    checks = db.execute(
        select(InvestigationCheckEntity).where(InvestigationCheckEntity.investigation_id == investigation.id).order_by(InvestigationCheckEntity.id)
    ).scalars().all()
    return {
        **summary_dict(investigation),
        "checks": [
            {"ref": check.ref, "round": check.round, "tool": check.tool, "purpose": check.purpose, "query": check.query, "ok": check.ok, "result": check.result, "at": _iso(check.created_at)}
            for check in checks
        ],
        "steps": [
            {
                "id": step.id, "round": step.round, "position": step.position, "kind": step.kind, "status": step.status,
                "title": step.title, "why": step.why, "result": step.result, "evidence": list(step.evidence or []),
                "unverified": step.unverified, "mark": step.mark, "note": step.note, "marked_by": step.marked_by,
            }
            for step in _steps(db, investigation.id)
        ],
    }


def _run_in_background(investigation_id: int, client: LLMClient, config: AlertEnrichmentConfig) -> None:
    def task() -> None:
        with get_session_local()() as db:
            try:
                investigation = db.get(InvestigationEntity, investigation_id)
                finding = db.get(FindingEntity, investigation.finding_id) if investigation else None
                if investigation is None or finding is None:
                    return
                context = finding_context(db, finding)
                loop.run_round(db, investigation_id, client, toolbox_for(db, context, config, investigation.skipped_sources or []))
            except Exception:  # noqa: BLE001 - a round must end in a state the dialog can show
                logger.exception("Investigation %s failed", investigation_id)
                db.rollback()
                investigation = db.get(InvestigationEntity, investigation_id)
                if investigation is not None:
                    investigation.status, investigation.ending = "failed", "ai_failed"
                    investigation.ending_detail = "Something went wrong while investigating. The steps so far are kept."
                    db.commit()

    submit(task)


def toolbox_for(db: Session, context: FindingContext, config: AlertEnrichmentConfig, skipped: list[str]) -> ToolBox:
    connection = get_prometheus_connections().get(context.connection_id)
    if connection is None:
        raise HTTPException(status_code=400, detail="The Prometheus connection this finding came from isn't set up any more.")
    return ToolBox(db, context, PrometheusQueryService(connection), config.service_labels, config.service_aliases, skipped)


def _steps(db: Session, investigation_id: int) -> list[InvestigationStepEntity]:
    return list(
        db.execute(
            select(InvestigationStepEntity).where(InvestigationStepEntity.investigation_id == investigation_id).order_by(InvestigationStepEntity.position)
        ).scalars()
    )


def _finding(db: Session, finding_id: int) -> FindingEntity:
    finding = db.get(FindingEntity, finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="finding not found")
    return finding


def _investigation(db: Session, investigation_id: int) -> InvestigationEntity:
    investigation = db.get(InvestigationEntity, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="investigation not found")
    return investigation


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
