"""Schemas for operational memory API requests and responses."""

from datetime import datetime

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
