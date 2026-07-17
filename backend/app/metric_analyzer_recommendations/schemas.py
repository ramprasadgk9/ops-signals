from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class MetricSampleOut(BaseModel):
    service: str
    metric_name: str
    analysis_run_id: str | None = None
    sample_count: int
    start_time: datetime
    end_time: datetime
    sampling_interval_seconds: int | None = None
    missing_ratio: float = 0.0
    min_value: float | None = None
    max_value: float | None = None
    mean_value: float | None = None
    stddev_value: float | None = None


class MetricProfileOut(BaseModel):
    sample_count: int
    start_time: datetime
    end_time: datetime
    sampling_interval_seconds: int | None = None
    regular_sampling: bool
    missing_ratio: float
    duplicate_timestamps: int
    constant_value_ratio: float
    mean: float
    stddev: float
    minimum: float
    maximum: float
    variance: float
    trend_slope: float
    trend_strength: float
    autocorrelation: float | None = None
    seasonality_strength: float
    sparsity: float
    metric_behavior: str


class AnalyzerRecommendationOut(BaseModel):
    analyzer_id: str
    display_name: str
    recommendation: str
    fitness_score: float
    decision_confidence: float
    summary: str
    evidence: dict = Field(default_factory=dict)
    requirements: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    parameters_tested: dict = Field(default_factory=dict)


class RecommendationResponseOut(BaseModel):
    sample: MetricSampleOut
    profile: MetricProfileOut
    recommendations: list[AnalyzerRecommendationOut]


class TimeValuePointIn(BaseModel):
    timestamp: datetime
    value: float


class MetricContextIn(BaseModel):
    metric_id: str | None = None
    sample_id: int | None = None
    metric_name: str
    metric_description: str
    metric_type: str | None = None
    provider: str | None = None
    unit: str | None = None
    operational_purpose: str
    use_cases: list[str] = Field(default_factory=list)
    operational_questions: list[str] = Field(default_factory=list)
    example_values: list[TimeValuePointIn] = Field(default_factory=list)
    additional_notes: str | None = None


class AnalyzerRecommendationRequestIn(BaseModel):
    conversation_id: str | None = None
    message: str
    metric_context: MetricContextIn
    options: dict = Field(default_factory=dict)


class NormalizedGoalOut(BaseModel):
    goal_id: str
    display_name: str
    source_text: str


class AnalyzerRecommendationChatResponseOut(BaseModel):
    conversation_id: str
    evaluation_id: int | None = None
    response_type: str
    recommendation_mode: Literal["preliminary", "evaluated"]
    assistant_message: dict
    recommendations: list[AnalyzerRecommendationOut]
    suggested_questions: list[str] = Field(default_factory=list)
    context_hash: str
    context_version: int
    normalized_goals: list[NormalizedGoalOut] = Field(default_factory=list)
    stale: bool = False
