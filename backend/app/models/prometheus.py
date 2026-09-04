from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PrometheusConnectionOut(BaseModel):
    id: str
    name: str
    base_url: str | None = None
    configured: bool


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


class DirectPrometheusAnalysisRequest(PrometheusQueryRequest):
    service: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    analyzer: str | None = None
    execution_mode: Literal["persist"] = "persist"


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
