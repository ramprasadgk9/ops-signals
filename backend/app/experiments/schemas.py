from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ExperimentDatasetOut(BaseModel):
    name: str
    file_path: str
    rows: int
    columns: int
    timestamp_column: str
    value_column: str
    sampling_interval_seconds: int | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    min_value: float | None = None
    max_value: float | None = None
    missing_values: int = 0
    duplicate_timestamps: int = 0
    timestamps_sorted: bool = True


class ExperimentAnalyzerOut(BaseModel):
    name: str
    algorithm: str | None = None
    model: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class ExperimentPreprocessingOut(BaseModel):
    normalization: str = "none"


class ExperimentExecutionOut(BaseModel):
    status: str = "completed"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    execution_time_seconds: float | None = None


class ExperimentEventOut(BaseModel):
    event_id: str
    event_type: str
    index: int | None = None
    timestamp: datetime | None = None
    value: float | None = None
    severity: str | None = None
    score: float | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    interpretation: str | None = None
    technical_summary: str | None = None


class ExperimentResultsOut(BaseModel):
    event_type: str
    event_count: int
    events: list[ExperimentEventOut]


class ExperimentMetricsOut(BaseModel):
    precision: float | None = None
    recall: float | None = None
    f1_score: float | None = None


class ExperimentArtifactsOut(BaseModel):
    raw_plot: str | None = None
    result_plot: str | None = None
    comparison_plot: str | None = None


class ExperimentRecommendationOut(BaseModel):
    title: str | None = None
    summary: str | None = None
    recommended_configuration: str | None = None
    suitable_for: list[str] = Field(default_factory=list)
    not_suitable_for: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ExperimentResultOut(BaseModel):
    experiment_id: str
    dataset: ExperimentDatasetOut
    analyzer: ExperimentAnalyzerOut
    preprocessing: ExperimentPreprocessingOut
    execution: ExperimentExecutionOut
    results: ExperimentResultsOut
    metrics: ExperimentMetricsOut = Field(default_factory=ExperimentMetricsOut)
    artifacts: ExperimentArtifactsOut = Field(default_factory=ExperimentArtifactsOut)
    observations: list[str] = Field(default_factory=list)
    recommendation: ExperimentRecommendationOut = Field(default_factory=ExperimentRecommendationOut)
    created_at: datetime
    plain_language_summary: str | None = None
    event_summaries: list[str] = Field(default_factory=list)


class ExperimentComparisonOut(BaseModel):
    analyzer: str
    comparison_summary: str
    shared_event_count: int
    unique_event_count: int
    experiment_ids: list[str]
    items: list[dict[str, Any]]
