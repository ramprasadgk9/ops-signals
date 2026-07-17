from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Capability:
    id: str
    title: str
    description: str
    analyzer_id: str
    enabled: bool = True
    supported_question_ids: list[str] = field(default_factory=list)