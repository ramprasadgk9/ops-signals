from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RoutingMode(str, Enum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"
    AUTOMATIC_WITH_OVERRIDE = "automatic_with_override"


@dataclass(slots=True)
class AnalyzerRoutingRequest:
    csv_path: str
    timestamp_column: str | None = None
    value_column: str | None = None
    routing_mode: RoutingMode = RoutingMode.AUTOMATIC_WITH_OVERRIDE
    selected_analyzers: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ValidationDecision:
    valid: bool
    status: str
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SeriesProfile:
    original_sample_count: int
    valid_sample_count: int
    invalid_timestamp_count: int
    invalid_value_count: int
    missing_percentage: float
    duplicate_timestamp_count: int
    sampling_interval_seconds: int | None
    duration_seconds: int | None
    irregular_sampling_percentage: float
    interpolated_sample_count: int
    interpolated_percentage: float
    constant_value_percentage: float
    sample_count: int
    regular_sampling: bool
    mean: float
    stddev: float
    minimum: float
    maximum: float
    variance: float
    trend_slope: float
    trend_strength: float
    seasonality_strength: float
    spikiness: float
    shift_index: float
    autocorrelation: float | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AnalyzerDecision:
    analyzer: str
    display_name: str
    eligible: bool
    eligibility_score: float
    suitability_score: float
    final_score: float
    recommendation: str
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    explanation: str = ""
    parameters_tested: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AnalyzerRoutingResult:
    request: AnalyzerRoutingRequest
    validation: ValidationDecision
    profile: SeriesProfile
    analyzers: list[AnalyzerDecision]
    export_path: str | None = None
    summary: str = ""
