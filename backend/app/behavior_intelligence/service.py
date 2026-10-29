from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.behavior_intelligence.fact_extractor import extract_facts, input_signals
from backend.app.behavior_intelligence.finding_builder import build_evaluation
from backend.app.behavior_intelligence.loader import load_definitions
from backend.app.behavior_intelligence.repository import BehaviorFindingRepository
from backend.app.models.entities import BehaviorFindingEntity, SignalEntity
from backend.app.behavior_intelligence.models import BehaviorDefinition

logger = logging.getLogger(__name__)


class BehaviorIntelligenceService:
    def __init__(self, definitions_path: str | Path) -> None:
        self.definitions_path = Path(definitions_path)
        self._definitions = load_definitions(self.definitions_path)

    def list_definitions(self) -> list[dict[str, Any]]:
        return [asdict(definition) for definition in self._definitions]

    def definitions(self) -> list[BehaviorDefinition]:
        return list(self._definitions)

    def evaluate(self, signals: list[dict[str, Any]], db: Session) -> list[BehaviorFindingEntity]:
        """Rules matched by the signals of one analysis run (one service)."""
        if not signals or not self._definitions:
            return []
        repository = BehaviorFindingRepository(db)
        service = str(signals[0].get("service")) if signals[0].get("service") else None
        analysis_run_id = str(signals[0].get("analysis_run_id")) if signals[0].get("analysis_run_id") else None
        return [repository.save_or_bump(record) for record, _runs in self._matches(signals, service, analysis_run_id)]

    def evaluate_across_runs(self, signals: list[dict[str, Any]], db: Session) -> list[BehaviorFindingEntity]:
        """Rules matched across the runs of one scheduled analysis or OTLP cycle, which analyzes each
        metric in its own run, so a rule over two metrics never matches inside one of them.

        Signals are grouped by service. A match is kept only when its inputs came from at least two
        runs; one whose inputs all came from one run was already found when that run was evaluated.
        The match is stored under its first input's run, and correlation_json["analysis_run_ids"]
        lists every input's run, so the findings it was made from can be linked back to it."""
        if not signals or not self._definitions:
            return []
        by_service: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
        for signal in signals:
            by_service[str(signal["service"]) if signal.get("service") else None].append(signal)
        repository = BehaviorFindingRepository(db)
        created: list[BehaviorFindingEntity] = []
        for service, service_signals in by_service.items():
            if len({signal.get("analysis_run_id") for signal in service_signals}) < 2:
                continue
            for record, runs in self._matches(service_signals, service, None):
                if len(runs) < 2:
                    continue
                record.analysis_run_id = runs[0]
                record.behavior_id = f"{record.definition_id}:{record.definition_version}:{runs[0]}"
                record.correlation_json = {**(record.correlation_json or {}), "analysis_run_ids": runs}
                created.append(repository.save_or_bump(record))
        return created

    def _matches(
        self, signals: list[dict[str, Any]], service: str | None, analysis_run_id: str | None
    ) -> Iterator[tuple[BehaviorFindingEntity, list[str]]]:
        """Each enabled rule these signals match, as an unsaved finding, with the runs its inputs'
        signals came from (first input's run first)."""
        for definition in self._definitions:
            if not definition.enabled:
                continue
            matched_inputs: dict[str, dict[str, Any]] = {}
            runs: list[str] = []
            for item in definition.inputs:
                item_signals = input_signals(item.metric_names, item.analyzers, signals)
                if not item_signals:
                    break
                matched_inputs[item.alias] = extract_facts(item_signals)[str(item_signals[0].get("metric_name"))]
                for run in sorted({str(signal["analysis_run_id"]) for signal in item_signals if signal.get("analysis_run_id")}):
                    if run not in runs:
                        runs.append(run)
            if len(matched_inputs) < len(definition.inputs):
                continue
            facts: dict[str, Any] = dict(matched_inputs)
            evaluation = build_evaluation(definition, facts, matched_inputs, service, analysis_run_id)
            if not evaluation.matched:
                continue
            yield (
                BehaviorFindingEntity(
                    behavior_id=f"{definition.id}:{evaluation.definition_version}:{analysis_run_id or 'unknown'}",
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
                ),
                runs,
            )


DEFINITIONS_PATH = Path(__file__).resolve().parents[3] / "config" / "behavior_definitions.d"


def evaluate_runs_together(db: Session, analysis_run_ids: list[str], definitions_path: str | Path = DEFINITIONS_PATH) -> int:
    """Evaluate behavior rules over the stored signals of several runs at once (a scheduled analysis
    or an OTLP cycle, one run per metric). Returns how many matches were stored or bumped. Never
    raises: a pattern that can't be evaluated must not fail the analysis it follows."""
    run_ids = sorted({run_id for run_id in analysis_run_ids if run_id})
    if len(run_ids) < 2 or not Path(definitions_path).exists():
        return 0
    try:
        rows = db.execute(select(SignalEntity).where(SignalEntity.analysis_run_id.in_(run_ids))).scalars().all()
        signals = [
            {
                "id": row.signal_id,
                "signal_type": row.signal_type,
                "analyzer_id": row.analyzer_id,
                "metric_name": row.metric_name,
                "service": row.service,
                "severity": row.severity,
                "confidence": row.confidence,
                "start_time": row.start_time,
                "end_time": row.end_time,
                "summary": row.summary,
                "evidence": row.evidence_json or {},
                "importance_score": row.importance_score,
                "analysis_run_id": row.analysis_run_id,
            }
            for row in rows
        ]
        return len(BehaviorIntelligenceService(definitions_path).evaluate_across_runs(signals, db))
    except Exception:
        logger.exception("Evaluating behavior rules across %d runs failed", len(run_ids))
        db.rollback()
        return 0
