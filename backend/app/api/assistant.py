"""Unified Operational Intelligence Assistant API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.assistant.knowledge_bootstrap import (
    ApplicationKnowledgeBootstrapResult,
    ApplicationKnowledgeBootstrapService,
    ApplicationKnowledgeStatus,
)
from backend.app.assistant import feedback
from backend.app.assistant.schemas import (
    AssistantChatRequest,
    AssistantChatResponse,
    AssistantFeedbackCreate,
    AssistantFeedbackOut,
    AssistantFeedbackUpdate,
    FlaggedQuestion,
)
from backend.app.assistant.service import OperationalIntelligenceAssistant
from backend.app.config import get_security_config
from backend.app.models.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

_services = {
    "assistant": None,
    "knowledge_bootstrap": None,
}


def get_assistant() -> OperationalIntelligenceAssistant | None:
    return _services["assistant"]


def get_knowledge_bootstrap() -> ApplicationKnowledgeBootstrapService | None:
    return _services["knowledge_bootstrap"]


@router.post("/chat", response_model=AssistantChatResponse)
def chat_assistant(
    payload: AssistantChatRequest,
    db: Session = Depends(get_db),
    assistant: OperationalIntelligenceAssistant | None = Depends(get_assistant),
) -> AssistantChatResponse:
    if not assistant:
        raise HTTPException(status_code=503, detail="Assistant is not initialized")
    try:
        return assistant.chat(payload, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Assistant chat failed: {e}")
        raise HTTPException(status_code=500, detail=f"Assistant chat failed: {str(e)}")


@router.get("/knowledge/status", response_model=ApplicationKnowledgeStatus)
def knowledge_status(
    bootstrap: ApplicationKnowledgeBootstrapService | None = Depends(get_knowledge_bootstrap),
) -> ApplicationKnowledgeStatus:
    if not bootstrap:
        raise HTTPException(status_code=503, detail="Assistant knowledge bootstrap is not initialized")
    status = bootstrap.get_status()
    status.docs_authoring_enabled = get_security_config().allow_file_writes
    return status


@router.post("/knowledge/bootstrap", response_model=ApplicationKnowledgeBootstrapResult)
def bootstrap_knowledge(
    force: bool = False,
    bootstrap: ApplicationKnowledgeBootstrapService | None = Depends(get_knowledge_bootstrap),
) -> ApplicationKnowledgeBootstrapResult:
    if not bootstrap:
        raise HTTPException(status_code=503, detail="Assistant knowledge bootstrap is not initialized")
    return bootstrap.bootstrap(force=force)


@router.post("/feedback", response_model=AssistantFeedbackOut, status_code=201)
def create_feedback(payload: AssistantFeedbackCreate, db: Session = Depends(get_db)) -> AssistantFeedbackOut:
    return feedback.record_feedback(db, payload)


@router.patch("/feedback/{feedback_id}", response_model=AssistantFeedbackOut)
def patch_feedback(feedback_id: int, payload: AssistantFeedbackUpdate, db: Session = Depends(get_db)) -> AssistantFeedbackOut:
    updated = feedback.update_feedback(db, feedback_id, payload)
    if updated is None:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return updated


@router.get("/feedback/flagged", response_model=list[FlaggedQuestion])
def list_flagged_questions(limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)) -> list[FlaggedQuestion]:
    return feedback.flagged_questions(db, limit=limit)
