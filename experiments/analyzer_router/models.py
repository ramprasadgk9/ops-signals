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
    trend_fit_r2: float = 0.0
    trend_abruptness_ratio: float = 0.0
    seasonality_dominant_lag: int | None = None
    seasonality_peak_strength: float = 0.0
    transient_spike_count: int = 0
    persistent_jump_count: int = 0
    # Strength of a daily or weekly cycle (see calendar_seasonality in feature_extractor.py) -
    # separate from seasonality_strength, which is built for sharp repeating shapes and reads a
    # smooth daily cycle as noise. Only seasonal_anomaly's scoring uses it today.
    calendar_seasonality_strength: float = 0.0
    calendar_seasonality_lag: int | None = None
    detected_profiles: list[str] = field(default_factory=list)
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
    routing_reason: str = ""
    parameters_tested: dict[str, Any] = field(default_factory=dict)
    # The series' detected behavioral profiles this analyzer supports (e.g. ["anomaly", "spike"]).
    matched_profiles: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AnalyzerRoutingResult:
    request: AnalyzerRoutingRequest
    validation: ValidationDecision
    profile: SeriesProfile
    analyzers: list[AnalyzerDecision]
    export_path: str | None = None
    summary: str = ""
