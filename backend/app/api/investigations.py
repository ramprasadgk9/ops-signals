"""Guided investigation of a finding (backend/app/investigation/). Reading is open to every role;
starting, continuing, stopping, marking steps and attaching to a case need an Editor (roles.py),
since a round runs queries and costs AI tokens."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.config import AlertEnrichmentConfig, get_alert_enrichment_config
from backend.app.identity import Actor, actor_name, current_actor
from backend.app.investigation import service
from backend.app.models.db import get_db

router = APIRouter(prefix="/api/investigations", tags=["investigations"])


class StartIn(BaseModel):
    finding_id: int
    note: str | None = Field(default=None, max_length=1000)
    # Also save the note to what the team knows about the service.
    save_note: bool = False
    # Sources to leave out: notes | changes | cases.
    skipped_sources: list[str] = Field(default_factory=list, max_length=3)


class ContinueIn(BaseModel):
    message: str | None = Field(default=None, max_length=1000)


class MarkIn(BaseModel):
    mark: Literal["found", "ruled_out"] | None = None
    note: str | None = Field(default=None, max_length=1000)


class AttachIn(BaseModel):
    case_id: int


@router.get("/start-info")
def start_info(finding_id: int = Query(...), db: Session = Depends(get_db)) -> dict[str, Any]:
    return service.start_info(db, finding_id, service.ai_client())


@router.get("")
def list_investigations(
    finding_id: int | None = Query(default=None),
    case_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return service.list_for(db, finding_id=finding_id, case_id=case_id)


@router.post("")
def start_investigation(
    payload: StartIn,
    db: Session = Depends(get_db),
    config: AlertEnrichmentConfig = Depends(get_alert_enrichment_config),
    actor: Actor | None = Depends(current_actor),
) -> dict[str, Any]:
    return service.start(
        db,
        payload.finding_id,
        client=service.ai_client(),
        config=config,
        note=payload.note,
        save_note=payload.save_note,
        skipped=payload.skipped_sources,
        by=actor_name(actor),
    )


@router.get("/{investigation_id}")
def get_investigation(investigation_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    return service.get(db, investigation_id)


@router.post("/{investigation_id}/continue")
def continue_investigation(
    investigation_id: int,
    payload: ContinueIn,
    db: Session = Depends(get_db),
    config: AlertEnrichmentConfig = Depends(get_alert_enrichment_config),
) -> dict[str, Any]:
    return service.continue_investigation(db, investigation_id, client=service.ai_client(), config=config, message=payload.message)


@router.post("/{investigation_id}/stop")
def stop_investigation(investigation_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    return service.stop(db, investigation_id)


@router.patch("/{investigation_id}/steps/{step_id}")
def mark_step(
    investigation_id: int,
    step_id: int,
    payload: MarkIn,
    db: Session = Depends(get_db),
    actor: Actor | None = Depends(current_actor),
) -> dict[str, Any]:
    return service.mark_step(db, investigation_id, step_id, mark=payload.mark, note=payload.note, by=actor_name(actor))


@router.post("/{investigation_id}/case")
def attach_to_case(
    investigation_id: int,
    payload: AttachIn,
    db: Session = Depends(get_db),
    actor: Actor | None = Depends(current_actor),
) -> dict[str, Any]:
    return service.attach_to_case(db, investigation_id, payload.case_id, actor_name(actor))
