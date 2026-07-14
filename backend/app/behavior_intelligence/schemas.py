from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BehaviorConditionOut(BaseModel):
    fact: str
    operator: str
    value: object
    passed: bool


class BehaviorEvaluationOut(BaseModel):
    definition_id: str
    definition_version: int
    title: str
    description: str
    matched: bool
    confidence: float
    service: str | None = None
    analysis_run_id: str | None = None
    facts: dict = Field(default_factory=dict)
    matched_conditions: list[BehaviorConditionOut] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    correlation: dict = Field(default_factory=dict)


class BehaviorDefinitionOut(BaseModel):
    id: str
    enabled: bool
    version: int
    title: str
    description: str
    scope: dict = Field(default_factory=dict)
    inputs: list[dict] = Field(default_factory=list)
    conditions: dict = Field(default_factory=dict)
    correlation: dict = Field(default_factory=dict)
    output: dict = Field(default_factory=dict)


class BehaviorFindingOut(BaseModel):
    id: int
    behavior_id: str
    definition_id: str
    definition_version: int
    title: str
    summary: str
    category: str
    severity: str
    service: str | None = None
    analysis_run_id: str | None = None
    input_metrics_json: dict = Field(default_factory=dict)
    facts_json: dict = Field(default_factory=dict)
    evidence_json: list[str] = Field(default_factory=list)
    matched_conditions_json: list[dict] = Field(default_factory=list)
    confidence: float
    correlation_json: dict = Field(default_factory=dict)
    case_id: int | None = None
    created_at: datetime
