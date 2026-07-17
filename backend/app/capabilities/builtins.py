from __future__ import annotations

from backend.app.capabilities.schema import Capability


BUILTIN_CAPABILITIES: list[Capability] = [
    Capability(
        id="baseline_analysis",
        title="Baseline Analysis",
        description="Detects sustained changes in the normal operating level.",
        analyzer_id="baseline_shift",
        enabled=True,
        supported_question_ids=[
            "what_changed",
            "baseline_changes",
            "behavior_novelty",
            "service_health",
        ],
    ),
    Capability(
        id="change_point_analysis",
        title="Change Point Analysis",
        description="Detects persistent changes in the metric baseline.",
        analyzer_id="ruptures",
        enabled=True,
        supported_question_ids=[
            "what_changed",
            "baseline_changes",
            "behavior_novelty",
            "service_health",
            "long_term_trends",
        ],
    ),
    Capability(
        id="trend_analysis",
        title="Trend Analysis",
        description="Detects long-term metric direction and velocity changes.",
        analyzer_id="trend",
        enabled=True,
        supported_question_ids=[
            "what_changed",
            "long_term_trends",
            "service_health",
            "investigation_priority",
        ],
    ),
    Capability(
        id="anomaly_detection",
        title="Anomaly Detection",
        description="Detects unusual behavior windows with statistically significant deviations.",
        analyzer_id="anomaly_zscore",
        enabled=True,
        supported_question_ids=[
            "unusual_activity",
            "investigation_priority",
            "what_changed",
            "service_health",
        ],
    ),
]

UNAVAILABLE_CAPABILITIES: list[dict[str, str]] = [
    {"id": "pattern_discovery", "title": "Pattern Discovery", "status": "not_installed"},
    {"id": "seasonality", "title": "Seasonality Analysis", "status": "not_installed"},
    {"id": "oscillation_detection", "title": "Oscillation Detection", "status": "not_installed"},
    {"id": "forecasting", "title": "Forecasting", "status": "not_installed"},
    {"id": "recovery_detection", "title": "Recovery Detection", "status": "not_installed"},
]
