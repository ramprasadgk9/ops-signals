from __future__ import annotations

from pydantic import BaseModel, Field


class Capability(BaseModel):
    id: str
    title: str
    description: str
    analyzer_id: str
    enabled: bool = True
    supported_question_ids: list[str] = Field(default_factory=list)
