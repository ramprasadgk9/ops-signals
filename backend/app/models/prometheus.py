from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PrometheusConnectionOut(BaseModel):
    id: str
    name: str
    base_url: str | None = None
    configured: bool
    is_default: bool = False
    match_labels: dict[str, str] = Field(default_factory=dict)
    # The label that tells clusters apart on this connection; None when turned off.
    cluster_label: str | None = None


class PrometheusConnectionsOut(BaseModel):
    connections: list[PrometheusConnectionOut]


class PrometheusLabelValuesOut(BaseModel):
    connection_id: str
    label: str
    values: list[str]


class PrometheusConnectionTestRequest(BaseModel):
    connection_id: str = "default"


class PrometheusConnectionTestOut(BaseModel):
    available: bool
    version: str | None = None
    latency_ms: int | None = None
    message: str


class PrometheusQueryRequest(BaseModel):
    connection_id: str = "default"
    query: str = Field(min_length=1)
    start: datetime
    end: datetime
    step: str = "5m"


class PrometheusSeriesSample(BaseModel):
    timestamp: datetime
    value: float


class PrometheusSeriesOut(BaseModel):
    labels: dict[str, str]
    samples: list[PrometheusSeriesSample]


class OddSeriesOut(BaseModel):
    value: str
    message: str


class PodSplitOut(BaseModel):
    """The query returned one series per pod (or instance): how to read them as one line."""

    label: str
    # The odd one out first, then the rest by name.
    values: list[str]
    suggested_combine: Literal["max", "sum", "avg", "min"]
    # Combined query per choice, and a one-pod query per value (plain selectors only).
    queries: dict[str, str]
    one_queries: dict[str, str] = Field(default_factory=dict)
    odd: OddSeriesOut | None = None


class CombinedSeriesOut(BaseModel):
    """What an analysis run combined: `how` across `count` values of `label`."""

    label: str
    count: int
    how: Literal["max", "sum", "avg", "min"]
    original_query: str
    odd: OddSeriesOut | None = None


class PrometheusPreviewOut(BaseModel):
    query: str
    start: datetime
    end: datetime
    step: str
    step_seconds: int
    series_count: int
    sample_count: int
    series: list[PrometheusSeriesOut]
    warnings: list[str] = Field(default_factory=list)
    pods: PodSplitOut | None = None


class DirectPrometheusAnalysisRequest(PrometheusQueryRequest):
    service: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    analyzer: str | None = None
    execution_mode: Literal["persist"] = "persist"
    # When the query returns one series per pod: combine them ("auto" = the metric's usual way, as
    # scheduled runs do) instead of refusing. None keeps the query exactly as written.
    combine: Literal["auto", "max", "sum", "avg", "min"] | None = None


class DirectPrometheusAnalysisOut(BaseModel):
    analysis_run_id: str
    provider: str = "prometheus"
    source_type: str = "prometheus"
    connection_id: str
    connection_name: str
    service: str
    metric_name: str
    query: str
    requested_start: datetime
    requested_end: datetime
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    step: str
    step_seconds: int
    sample_count: int
    series_count: int
    findings_count: int
    signal_count: int
    behavior_findings_count: int
    warnings: list[str] = Field(default_factory=list)
    analyzer_selection_mode: str = "all"
    analyzer_routing: list[dict] = Field(default_factory=list)
    executed_analyzers: list[str] = Field(default_factory=list)
    analyzer_executions: list[dict] = Field(default_factory=list)
    series: list[PrometheusSeriesOut] = Field(default_factory=list)
    signals: list[dict] = Field(default_factory=list)
    findings: list[dict] = Field(default_factory=list)
    combined: CombinedSeriesOut | None = None
