from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class BehaviorCondition:
    fact: str
    operator: str
    value: object


@dataclass(slots=True)
class BehaviorInput:
    alias: str
    metric_name: str
    analyzers: list[str] = field(default_factory=list)
    # Other names the same metric arrives under (an OTel or Prometheus name for memory_usage).
    # The input matches the first of metric_name, then these, that has signals.
    aliases: list[str] = field(default_factory=list)

    @property
    def metric_names(self) -> list[str]:
        return list(dict.fromkeys([self.metric_name, *self.aliases]))


@dataclass(slots=True)
class BehaviorOutput:
    category: str
    severity: str
    title: str
    summary: str
    evidence: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BehaviorDefinition:
    id: str
    enabled: bool
    version: int
    title: str
    description: str
    scope: dict
    inputs: list[BehaviorInput]
    conditions: dict[str, list[BehaviorCondition]]
    correlation: dict
    output: BehaviorOutput
    source_file: str | None = None


@dataclass(slots=True)
class BehaviorEvaluation:
    definition_id: str
    definition_version: int
    title: str
    description: str
    matched: bool
    confidence: float
    service: str | None
    analysis_run_id: str | None
    facts: dict
    matched_conditions: list[dict]
    evidence: list[str]
    correlation: dict
