from __future__ import annotations

QUESTION_CATALOG: list[dict[str, str | int | bool]] = [
    {
        "id": "what_changed",
        "label": "What changed yesterday?",
        "description": "Summarize important changes in the selected analysis window.",
        "display_order": 1,
        "enabled": True,
    },
    {
        "id": "investigation_priority",
        "label": "What should I investigate first?",
        "description": "Rank the most important findings.",
        "display_order": 2,
        "enabled": True,
    },
    {
        "id": "unusual_activity",
        "label": "Did anything unusual happen?",
        "description": "Show unexpected metric behavior.",
        "display_order": 3,
        "enabled": True,
    },
    {
        "id": "behavior_novelty",
        "label": "Is this behaviour new or expected?",
        "description": "Compare current behavior with the previous window.",
        "display_order": 4,
        "enabled": True,
    },
    {
        "id": "historical_similarity",
        "label": "Has this happened before?",
        "description": "Search for similar historical findings.",
        "display_order": 5,
        "enabled": True,
    },
    {
        "id": "baseline_changes",
        "label": "Show baseline changes",
        "description": "Display sustained changes in the normal metric level.",
        "display_order": 6,
        "enabled": True,
    },
    {
        "id": "long_term_trends",
        "label": "Show long-term trends",
        "description": "Show whether the metric is rising, falling, or stable.",
        "display_order": 7,
        "enabled": True,
    },
    {
        "id": "service_health",
        "label": "Is the service healthy?",
        "description": "Summarize overall health using the available analyzers.",
        "display_order": 8,
        "enabled": True,
    },
]
