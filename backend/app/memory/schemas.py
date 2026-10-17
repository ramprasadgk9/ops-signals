"""Schemas for operational memory API requests and responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from backend.app.memory.novelty import Novelty


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


class MemoryStatsResponse(BaseModel):
    """Authoritative memory counts from operational case metadata."""

    generated_at: datetime
    enabled: bool
    status: str
    indexed_cases: int
    not_indexed_cases: int
    stale_cases: int
    error_cases: int
    total_cases: int
    # Cases catch-up indexing will still add (memory/catch_up.py): left out by an outage.
    waiting_to_index: int = 0
    source: str = "ops_operational_cases.memory_status"


class SimilarCaseMatch(BaseModel):
    """A single similar case match from the similarity search."""

    case_id: int
    similarity_score: float = Field(description="Score between 0 and 1")
    title: str
    service: str | None = None
    # None for an imported incident, which comes from a postmortem rather than a metric.
    metric_name: str | None = None
    category: str | None = None
    origin: str = "detected"
    source: str | None = None
    source_id: str | None = None
    # "strong" (>= 0.70) or "possible" (>= 0.40); see similarity_service.match_strength.
    strength: str = "strong"
    same_service: bool = False
    case_status: str
    investigation_status: str
    rca_verified: bool
    root_cause_summary: str | None = None
    corrective_action: str | None = None
    outcome_status: str | None = None
    outcome_summary: str | None = None
    # Near-copies of this match (same service, same symptom, cause and fix), folded under it so
    # one recurring incident can't fill every slot (diversity.collapse_near_copies).
    more_like_this: list["SimilarCaseMatch"] = Field(default_factory=list)


class SimilarCasesResponse(BaseModel):
    """Response containing similar operational cases."""

    source_case_id: int
    similarity_type: str = "finding_similarity"
    matches: list[SimilarCaseMatch]
    novelty: Novelty | None = None


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


class AlertContextOutcome(BaseModel):
    """A single prior learning outcome for the same service/metric."""

    outcome_status: str
    root_cause_category: str | None = None
    resolution_summary: str | None = None
    confirmed_analyzers: list[str] = Field(default_factory=list)
    rejected_analyzers: list[str] = Field(default_factory=list)
    case_id: int
    resolved_at: datetime | None = None
    created_at: datetime


class AlertContextSimilarCase(BaseModel):
    """A semantically similar prior case, found from free-text alert context."""

    case_id: int
    similarity_score: float
    title: str
    case_status: str
    outcome_status: str | None = None
    root_cause_summary: str | None = None
    corrective_action: str | None = None
    outcome_summary: str | None = None
    origin: str = "detected"
    source: str | None = None
    source_id: str | None = None
    reference: str
    # Near-copies folded under this case (diversity.collapse_near_copies), counted, not listed.
    more_like_this: int = 0


class PastIncidentMatch(BaseModel):
    """A past case that looks like a finding, for the finding's "Seen before?" panel."""

    case_id: int
    title: str
    similarity_score: float
    strength: str
    same_service: bool
    service: str | None = None
    metric_name: str | None = None
    origin: str = "detected"
    source: str | None = None
    source_id: str | None = None
    source_url: str | None = None
    root_cause_summary: str | None = None
    corrective_action: str | None = None
    outcome_summary: str | None = None
    resolved_at: datetime | None = None
    reference: str
    # Near-copies of this match (same service, same symptom, cause and fix), folded under it so
    # one recurring incident can't fill every slot (diversity.collapse_near_copies).
    more_like_this: list["PastIncidentMatch"] = Field(default_factory=list)


class SeenBeforeResponse(BaseModel):
    """Past cases resembling a finding, found without opening a case for it."""

    finding_id: int
    available: bool
    reason: str | None = None
    service: str | None = None
    matches: list[PastIncidentMatch] = Field(default_factory=list)
    novelty: Novelty | None = None


class AlertContextHistory(BaseModel):
    """Aggregate counts of prior learning outcomes for this service/metric."""

    total_prior_occurrences: int
    confirmed: int
    rejected: int
    partially_confirmed: int
    inconclusive: int
    confirmed_rate: float | None = None
    most_common_root_cause: str | None = None
    last_seen_at: datetime | None = None


class AlertContextRawActivity(BaseModel):
    """Recurrence of this service/metric in raw Findings/BehaviorFindings, regardless of
    whether anyone ever filed a case for them. Weaker than a learning outcome or similar
    case - nobody recorded a root cause or fix for these - but it costs a human nothing
    to exist, so it's there even when the richer signals above are empty. Never used to
    compute `recommendation`: "this occurred before" and "this was confirmed real" are
    different claims and shouldn't be conflated."""

    finding_count: int
    behavior_count: int
    total_occurrences: int
    most_recent_at: datetime | None = None
    recent_titles: list[str] = Field(default_factory=list)
    ai_summary: str | None = Field(
        default=None,
        description="Optional AI-polished plain-language summary of the titles above. Additive "
        "only - grounded strictly in recent_titles/finding_count/behavior_count, never a "
        "replacement for them. None whenever AI is off or synthesis fails; callers should fall "
        "back to rendering finding_count/behavior_count/recent_titles directly.",
    )


class AlertContextResponse(BaseModel):
    """Decision-support context for an incoming alert, for an external alert manager
    to consult before firing - combines exact-match learning outcomes with
    semantically similar prior cases, plus raw finding/behavior recurrence for when
    no one ever filed a case."""

    service: str | None = None
    metric_name: str
    history: AlertContextHistory
    exact_match_outcomes: list[AlertContextOutcome]
    similar_cases: list[AlertContextSimilarCase]
    raw_activity: AlertContextRawActivity
    recommendation: str = Field(description="One of: likely_real, likely_noise, insufficient_history")
    recommendation_basis: str
