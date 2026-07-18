"""Schemas for operational memory API requests and responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class MemoryIndexResponse(BaseModel):
    """Response when indexing a case into operational memory."""

    case_id: int
    memory_status: str
    collection: str
    embedding_model: str
    content_version: int
    indexed_at: datetime


class MemoryStatusResponse(BaseModel):
    """Response showing current memory status of a case."""

    case_id: int
    memory_status: str
    memory_indexed_at: datetime | None = None
    memory_content_version: int | None = None
    memory_error: str | None = None


class MemoryHealthResponse(BaseModel):
    """Response showing overall memory system health."""

    enabled: bool
    provider: str
    status: str
    collection: str
    embedding_model: str
    dimension: int


class SimilarCaseMatch(BaseModel):
    """A single similar case match from the similarity search."""

    case_id: int
    similarity_score: float = Field(description="Score between 0 and 1")
    title: str
    service: str | None = None
    metric_name: str
    category: str | None = None
    case_status: str
    investigation_status: str
    rca_verified: bool
    root_cause_summary: str | None = None
    corrective_action: str | None = None
    outcome_status: str | None = None
    outcome_summary: str | None = None


class SimilarCasesResponse(BaseModel):
    """Response containing similar operational cases."""

    source_case_id: int
    similarity_type: str = "finding_similarity"
    matches: list[SimilarCaseMatch]


class MemoryChatRequest(BaseModel):
    """Request for conversational retrieval over operational memory."""

    conversation_id: UUID | None = None
    message: str = Field(min_length=1)
    case_id: int | None = None
    top_k: int = Field(default=5, ge=1, le=10)
    minimum_score: float = Field(default=0.55, ge=0.0, le=1.0)
    same_service_only: bool = False


class MemoryChatSource(BaseModel):
    """A source case surfaced in chat."""

    case_id: int
    title: str
    similarity_score: float
    service: str | None = None
    metric_name: str | None = None
    category: str | None = None
    case_status: str
    root_cause_summary: str | None = None
    outcome_summary: str | None = None


class MemoryChatResponse(BaseModel):
    """Response from the operational memory chat endpoint."""

    conversation_id: UUID
    answer: str
    limitations: list[str]
    suggested_questions: list[str]
    sources: list[MemoryChatSource]
