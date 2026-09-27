"""Unified Operational Intelligence Assistant API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.assistant.knowledge_bootstrap import (
    ApplicationKnowledgeBootstrapResult,
    ApplicationKnowledgeBootstrapService,
    ApplicationKnowledgeStatus,
)
from backend.app.assistant import feedback
from backend.app.assistant.starters import StarterQuestions, starter_questions
from backend.app.assistant.docs_check import (
    DocsCheckService,
    DocsCoverage,
    DraftQuestion,
    EvaluateRequest,
    EvaluateResult,
    GoldenSetError,
    SaveTestsRequest,
    SaveTestsResult,
)
from backend.app.assistant.schemas import (
    AssistantChatRequest,
    AssistantChatResponse,
    AssistantFeedbackCreate,
    AssistantFeedbackOut,
    AssistantFeedbackUpdate,
    FlaggedQuestion,
)
from backend.app.assistant.service import OperationalIntelligenceAssistant
from backend.app.config import SecurityConfig, get_security_config
from backend.app.security import require_file_writes
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


# --- Docs check ------------------------------------------------------------------------------------


def get_docs_check(
    bootstrap: ApplicationKnowledgeBootstrapService | None = Depends(get_knowledge_bootstrap),
    assistant: OperationalIntelligenceAssistant | None = Depends(get_assistant),
) -> DocsCheckService:
    if not bootstrap:
        raise HTTPException(status_code=503, detail="Assistant knowledge bootstrap is not initialized")
    return DocsCheckService(
        bootstrap=bootstrap,
        assistant=assistant,
        ai_services=assistant.services.ai_services if assistant else None,
        repo_root=bootstrap.repo_root,
    )


class DraftRequest(BaseModel):
    source_path: str
    limit: int = Field(default=5, ge=1, le=10)


@router.get("/docs-check/coverage", response_model=DocsCoverage)
def docs_coverage(service: DocsCheckService = Depends(get_docs_check)) -> DocsCoverage:
    return service.coverage()


@router.post("/docs-check/draft", response_model=list[DraftQuestion])
def draft_doc_questions(payload: DraftRequest, service: DocsCheckService = Depends(get_docs_check)) -> list[DraftQuestion]:
    try:
        return service.draft_questions(payload.source_path, limit=payload.limit)
    except GoldenSetError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/docs-check/evaluate", response_model=EvaluateResult)
def evaluate_doc_question(payload: EvaluateRequest, db: Session = Depends(get_db), service: DocsCheckService = Depends(get_docs_check)) -> EvaluateResult:
    try:
        return service.evaluate(payload, db)
    except GoldenSetError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/docs-check/tests", response_model=SaveTestsResult)
def save_doc_tests(
    payload: SaveTestsRequest,
    db: Session = Depends(get_db),
    service: DocsCheckService = Depends(get_docs_check),
    security: SecurityConfig = Depends(get_security_config),
) -> SaveTestsResult:
    """Appends questions to the golden set. `dry_run` only returns the YAML and needs no file writes."""
    if not payload.dry_run:
        require_file_writes(security)
    try:
        return service.save_tests(payload, db)
    except GoldenSetError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/starter-questions", response_model=StarterQuestions)
def get_starter_questions(db: Session = Depends(get_db)) -> StarterQuestions:
    """Example questions for the first screen, built from this install's findings and cases."""
    return starter_questions(db)
