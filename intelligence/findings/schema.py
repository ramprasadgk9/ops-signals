from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from intelligence.signals.schema import _sanitize_json


@dataclass(slots=True)
class OperationalFinding:
    id: int | None = None
    service: str | None = None
    metric_name: str = ""
    title: str = ""
    summary: str = ""
    category: str = ""
    health_status: str = "normal"
    importance_score: float = 0.0
    investigation_priority: int = 3
    signal_ids: list[str] = field(default_factory=list)
    comparison_json: dict[str, Any] = field(default_factory=dict)
    analysis_run_id: str | None = None
    created_at: datetime | None = None
    cluster: str | None = None

    def to_record(self) -> dict[str, Any]:
        payload = _sanitize_json(asdict(self))
        if payload.get("id") is None:
            payload.pop("id", None)
        if payload.get("created_at") is None:
            payload.pop("created_at", None)
        return payload
