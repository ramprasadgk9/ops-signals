from __future__ import annotations

from pydantic import BaseModel, Field


class Question(BaseModel):
    id: str
    label: str
    description: str
    enabled: bool = True
    display_order: int = 0


class AvailableQuestion(Question):
    contributors: list[str] = Field(default_factory=list)
    available: bool = True


class QuestionAnswerRequest(BaseModel):
    question_id: str
    service: str
    metric_name: str
    analysis_run_id: str


class QuestionAnswerResponse(BaseModel):
    question_id: str
    headline: str
    answer: str
    status: str
    priority: str
    confidence: float
    key_points: list[str] = Field(default_factory=list)
    evidence_signal_ids: list[str] = Field(default_factory=list)
