"""What a team knows about a service (backend/app/services/service_notes.py): read by everyone,
changed by Editors (roles.py: every write needs an Editor unless listed otherwise)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.config import AlertEnrichmentConfig, get_alert_enrichment_config
from backend.app.identity import Actor, actor_name, current_actor
from backend.app.models.db import get_db
from backend.app.services import service_notes
from backend.app.services.prometheus_service import PrometheusQueryService, resolve_prometheus_connection

router = APIRouter(prefix="/api/service-notes", tags=["service-notes"])


class DependencyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = "service"


class BehaviourIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    by: str | None = None
    at: str | None = None
    case_id: int | None = None


class ServiceNoteIn(BaseModel):
    depends_on: list[DependencyIn] = Field(default_factory=list, max_length=50)
    behaviours: list[BehaviourIn] = Field(default_factory=list, max_length=50)
    dismissed: list[str] = Field(default_factory=list, max_length=200)
    owner: str | None = Field(default=None, max_length=200)
    channel: str | None = Field(default=None, max_length=200)
    runbook_url: str | None = Field(default=None, max_length=1000)


@router.get("")
def list_service_notes(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return service_notes.all_notes(db)


@router.get("/{service}")
def get_service_note(service: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return service_notes.get_note(db, service)


@router.get("/{service}/suggestions")
def suggest_dependencies(
    service: str,
    connection_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    alert_config: AlertEnrichmentConfig = Depends(get_alert_enrichment_config),
) -> list[dict[str, str]]:
    """Dependencies named by labels on the service's own series. Empty when Prometheus can't be
    reached or nothing was found; never an error, since suggestions are extra."""
    try:
        connection = resolve_prometheus_connection(connection_id)
    except HTTPException:
        return []
    if not connection.base_url:
        return []
    note = service_notes.get_note(db, service)
    return service_notes.suggest_dependencies(
        PrometheusQueryService(connection), service, alert_config.service_labels, service_notes.known_names(note)
    )


@router.put("/{service}")
def save_service_note(
    service: str,
    payload: ServiceNoteIn,
    db: Session = Depends(get_db),
    actor: Actor | None = Depends(current_actor),
) -> dict[str, Any]:
    return service_notes.save_note(db, service, payload.model_dump(), actor_name(actor))
