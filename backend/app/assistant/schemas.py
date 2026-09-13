"""Schemas for the Operational Intelligence Assistant."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class AssistantChatRequest(BaseModel):
    conversation_id: UUID | None = None
    message: str = Field(min_length=1)
    case_id: int | None = None
    top_k: int = Field(default=5, ge=1, le=10)
    minimum_score: float = Field(default=0.55, ge=0.0, le=1.0)
    same_service_only: bool = False


class AssistantSource(BaseModel):
    source_type: str
    title: str
    score: float
    reference: str
    service: str | None = None
    metric_name: str | None = None
    summary: str | None = None


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
