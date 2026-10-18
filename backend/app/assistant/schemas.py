"""Schemas for the Operational Intelligence Assistant."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AssistantChatRequest(BaseModel):
    conversation_id: UUID | None = None
    message: str = Field(min_length=1)
    case_id: int | None = None
    top_k: int = Field(default=5, ge=1, le=10)
    # The case-memory floor, same as MemoryChatRequest (similarity_service.POSSIBLE_MATCH_SCORE).
    minimum_score: float = Field(default=0.40, ge=0.0, le=1.0)
    same_service_only: bool = False


class AssistantSource(BaseModel):
    source_type: str
    title: str
    score: float
    reference: str
    service: str | None = None
    metric_name: str | None = None
    summary: str | None = None
    # Documentation sources only: the file and the section within it that matched, e.g.
    # "docs/security-model.md" and "Turning on authentication". `reference` links to the section.
    source_path: str | None = None
    section: str | None = None
    # The passage of the matched section that answers the question, verbatim.
    quote: str | None = None
    # Internal: the whole section a windowed documentation chunk came from, to quote from.
    section_text: str | None = Field(default=None, exclude=True)


class AssistantEvidenceGroup(BaseModel):
    source_type: str
    label: str
    count: int
    sources: list[AssistantSource] = Field(default_factory=list)


class AssistantChatResponse(BaseModel):
    conversation_id: UUID
    intent: str
    routes: list[str] = Field(default_factory=list)
    knowledge_used: list[str] = Field(default_factory=list)
    answer: str
    ai_synthesis_used: bool = False
    limitations: list[str]
    suggested_questions: list[str]
    sources: list[AssistantSource]
    evidence_groups: list[AssistantEvidenceGroup] = Field(default_factory=list)


FeedbackReason = Literal["wrong_section", "missing_step", "outdated", "not_in_docs"]
FeedbackStatus = Literal["open", "added_as_test", "dismissed"]


class AssistantFeedbackCreate(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    helpful: bool
    reason: FeedbackReason | None = None
    answer: str | None = Field(default=None, max_length=20000)
    conversation_id: UUID | None = None
    ai_synthesis_used: bool = False
    cited: list[str] = Field(default_factory=list, max_length=10)


class AssistantFeedbackUpdate(BaseModel):
    reason: FeedbackReason | None = None
    status: FeedbackStatus | None = None


class AssistantFeedbackOut(BaseModel):
    id: int
    question: str
    helpful: bool
    reason: FeedbackReason | None = None
    status: FeedbackStatus = "open"
    created_at: datetime


class FlaggedQuestion(BaseModel):
    """Every open thumbs-down on the same question, however it was capitalised or spaced."""

    question: str
    count: int
    reasons: dict[str, int] = Field(default_factory=dict)
    cited: list[str] = Field(default_factory=list)
    feedback_ids: list[int] = Field(default_factory=list)
    last_flagged_at: datetime
