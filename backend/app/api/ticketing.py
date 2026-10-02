from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel

from backend.app.config import TicketingConfig, get_ticketing_config
from backend.app.integrations.ticketing.models import (
    AmbiguousResolutionRequest,
    TicketEventView,
    TicketOperationView,
    TicketView,
)
from backend.app.integrations.ticketing.protocols import (
    AmbiguousOutcomeError,
    ProviderNotConfiguredError,
    TicketingError,
)
from backend.app.integrations.ticketing.service import CaseTicketing
from backend.app.models.db import get_session_local

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ticketing"])

_ticketing_service: CaseTicketing | None = None


def get_ticketing_service(
    config: TicketingConfig | None = Depends(get_ticketing_config),
) -> CaseTicketing:
    global _ticketing_service
    if _ticketing_service is None:
        effective_config = config if isinstance(config, TicketingConfig) else get_ticketing_config()
        _ticketing_service = CaseTicketing(
            session_factory=lambda: get_session_local()(),
            config=effective_config,
        )
    return _ticketing_service



class CreateTicketRequest(BaseModel):
    provider: str | None = None
    idempotency_key: str | None = None


class LinkTicketRequest(BaseModel):
    display_key: str
    provider: str | None = None


class OperationIdRequest(BaseModel):
    operation_id: str


@router.post(
    "/api/cases/{case_id}/ticket/create",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TicketOperationView,
)
def create_case_ticket(
    case_id: int,
    payload: CreateTicketRequest | None = None,
    service: CaseTicketing = Depends(get_ticketing_service),
) -> TicketOperationView:
    try:
        provider = payload.provider if payload else None
        idem_key = payload.idempotency_key if payload else None
        return service.request_create(case_id, idempotency_key=idem_key, provider=provider)
    except ProviderNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TicketingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/api/cases/{case_id}/ticket/sync",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TicketOperationView,
)
def sync_case_ticket(
    case_id: int,
    payload: CreateTicketRequest | None = None,
    service: CaseTicketing = Depends(get_ticketing_service),
) -> TicketOperationView:
    try:
        provider = payload.provider if payload else None
        return service.request_sync(case_id, provider=provider)
    except ProviderNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TicketingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/api/cases/{case_id}/ticket/retry",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TicketOperationView,
)
def retry_ticket_operation(
    case_id: int,
    payload: OperationIdRequest,
    service: CaseTicketing = Depends(get_ticketing_service),
) -> TicketOperationView:
    try:
        return service.retry_operation(payload.operation_id)
    except TicketingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/api/cases/{case_id}/ticket/link",
    status_code=status.HTTP_200_OK,
    response_model=TicketView,
)
def link_existing_case_ticket(
    case_id: int,
    payload: LinkTicketRequest,
    service: CaseTicketing = Depends(get_ticketing_service),
) -> TicketView:
    try:
        provider = payload.provider or service.config.active_provider
        return service.link_existing_ticket(case_id, provider, payload.display_key)
    except ProviderNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TicketingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/api/cases/{case_id}/ticket/force-create",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TicketOperationView,
)
def force_create_case_ticket(
    case_id: int,
    payload: OperationIdRequest,
    service: CaseTicketing = Depends(get_ticketing_service),
) -> TicketOperationView:
    try:
        return service.force_create_ticket(case_id, payload.operation_id)
    except TicketingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/api/cases/{case_id}/ticket/resolve-ambiguity",
    status_code=status.HTTP_200_OK,
)
def resolve_ticket_ambiguity(
    case_id: int,
    payload: AmbiguousResolutionRequest,
    service: CaseTicketing = Depends(get_ticketing_service),
) -> Any:
    try:
        return service.resolve_ambiguity(case_id, payload)
    except ProviderNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AmbiguousOutcomeError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except TicketingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/api/cases/{case_id}/ticket",
    status_code=status.HTTP_200_OK,
    response_model=TicketView | None,
)
def get_case_ticket(
    case_id: int,
    provider: str | None = Query(default=None),
    service: CaseTicketing = Depends(get_ticketing_service),
) -> TicketView | None:
    return service.get_ticket_view(case_id, provider=provider)


@router.get(
    "/api/cases/{case_id}/ticket/events",
    status_code=status.HTTP_200_OK,
    response_model=list[TicketEventView],
)
def list_case_ticket_events(
    case_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    service: CaseTicketing = Depends(get_ticketing_service),
) -> list[TicketEventView]:
    return service.list_ticket_events(case_id, limit=limit)


@router.get(
    "/api/cases/{case_id}/ticket/operations/{operation_id}",
    status_code=status.HTTP_200_OK,
    response_model=TicketOperationView,
)
def get_ticket_operation(
    case_id: int,
    operation_id: str,
    service: CaseTicketing = Depends(get_ticketing_service),
) -> TicketOperationView:
    op = service.get_operation_view(operation_id)
    if not op or op.case_id != case_id:
        raise HTTPException(status_code=404, detail="Operation not found")
    return op


@router.post(
    "/api/integrations/ticketing/{provider}/webhook",
)
async def receive_ticketing_webhook(
    provider: str,
    request: Request,
    response: Response,
    service: CaseTicketing = Depends(get_ticketing_service),
) -> Any:
    raw_body = await request.body()
    status_code, result = service.accept_webhook(provider, raw_body, request.headers)
    response.status_code = status_code
    return result
