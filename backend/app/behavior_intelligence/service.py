from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.app.behavior_intelligence.fact_extractor import extract_facts
from backend.app.behavior_intelligence.finding_builder import build_evaluation
from backend.app.behavior_intelligence.loader import load_definitions
from backend.app.behavior_intelligence.repository import BehaviorFindingRepository
from backend.app.models.entities import BehaviorFindingEntity
from backend.app.behavior_intelligence.models import BehaviorDefinition


class BehaviorIntelligenceService:
    def __init__(self, definitions_path: str | Path) -> None:
        self.definitions_path = Path(definitions_path)
        self._definitions = load_definitions(self.definitions_path)

    def list_definitions(self) -> list[dict[str, Any]]:
        return [asdict(definition) for definition in self._definitions]

    def definitions(self) -> list[BehaviorDefinition]:
        return list(self._definitions)

    def evaluate(self, signals: list[dict[str, Any]], db: Session) -> list[BehaviorFindingEntity]:
        if not signals or not self._definitions:
            return []
        repository = BehaviorFindingRepository(db)
        service = str(signals[0].get("service")) if signals and signals[0].get("service") else None
        analysis_run_id = str(signals[0].get("analysis_run_id")) if signals and signals[0].get("analysis_run_id") else None
        created: list[BehaviorFindingEntity] = []
        for definition in self._definitions:
            if not definition.enabled:
                continue
            matched_inputs: dict[str, dict[str, Any]] = {}
            for item in definition.inputs:
                metric_signals = [
                    signal for signal in signals
                    if signal.get("metric_name") == item.metric_name
                    and (not item.analyzers or signal.get("analyzer_id") in item.analyzers)
                ]
                if metric_signals:
                    matched_inputs[item.alias] = extract_facts(metric_signals)[item.metric_name]
            if len(matched_inputs) < len(definition.inputs):
                continue
            facts: dict[str, Any] = {}
            for alias, metric_fact in matched_inputs.items():
                facts[alias] = metric_fact
            evaluation = build_evaluation(definition, facts, matched_inputs, service, analysis_run_id)
            if not evaluation.matched:
                continue
            behavior_id = f"{definition.id}:{evaluation.definition_version}:{analysis_run_id or 'unknown'}"
            record = BehaviorFindingEntity(
                behavior_id=behavior_id,
                definition_id=definition.id,
                definition_version=definition.version,
                title=definition.output.title,
                summary=definition.output.summary,
                category=definition.output.category,
                severity=definition.output.severity,
                service=service,
                analysis_run_id=analysis_run_id,
                input_metrics_json={item.alias: item.metric_name for item in definition.inputs},
                facts_json=facts,
                evidence_json=definition.output.evidence,
                matched_conditions_json=evaluation.matched_conditions,
                confidence=evaluation.confidence,
                correlation_json=evaluation.correlation,
            )
            created.append(repository.save_or_bump(record))
        return created
