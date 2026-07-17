from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class OperationalSignal:
    signal_type: str
    analyzer_id: str
    metric_name: str
    service: str | None
    env: str | None
    severity: str
    confidence: float
    start_time: datetime
    end_time: datetime
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)
    signal_id: str = field(default_factory=lambda: uuid4().hex)
    importance_score: float = 0.0
    status: str = "new"
    analysis_run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_json"] = payload.pop("evidence")
        return payload
