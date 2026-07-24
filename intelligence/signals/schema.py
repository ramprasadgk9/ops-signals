from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import math
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
        payload = _sanitize_json(asdict(self))
        payload["evidence_json"] = payload.pop("evidence")
        return payload


def _sanitize_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_json(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_json(item) for item in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value
