from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.behavior_intelligence.condition_evaluator import evaluate_conditions
from backend.app.behavior_intelligence.confidence import calculate_confidence
from backend.app.behavior_intelligence.fact_extractor import extract_facts
from backend.app.behavior_intelligence.finding_builder import build_evaluation
from backend.app.behavior_intelligence.loader import load_definitions
from backend.app.behavior_intelligence.schemas import BehaviorEvaluationOut, BehaviorFindingOut
from backend.app.behavior_intelligence.service import BehaviorIntelligenceService
from backend.app.models.db import get_db
from backend.app.models.entities import BehaviorFindingEntity, SignalEntity

router = APIRouter(prefix="/api/behavior-evaluations", tags=["behavior-evaluations"])


def _service() -> BehaviorIntelligenceService:
    return BehaviorIntelligenceService("config/behavior_definitions.d")


@router.get("", response_model=list[BehaviorFindingOut])
def list_behavior_findings(
    definition_id: str | None = None,
    service: str | None = None,
    analysis_run_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[BehaviorFindingOut]:
    query = select(BehaviorFindingEntity)
    if definition_id:
        query = query.where(BehaviorFindingEntity.definition_id == definition_id)
    if service:
        query = query.where(BehaviorFindingEntity.service == service)
    if analysis_run_id:
        query = query.where(BehaviorFindingEntity.analysis_run_id == analysis_run_id)
    rows = db.execute(query.order_by(BehaviorFindingEntity.created_at.desc())).scalars().all()
    return [BehaviorFindingOut.model_validate(row, from_attributes=True) for row in rows]


@router.get("/evaluate", response_model=list[BehaviorEvaluationOut])
def evaluate_behavior_definitions(
    analysis_run_id: str,
    service: str | None = None,
    db: Session = Depends(get_db),
) -> list[BehaviorEvaluationOut]:
    query = select(SignalEntity).where(SignalEntity.analysis_run_id == analysis_run_id)
    if service:
        query = query.where(SignalEntity.service == service)
    signals = db.execute(query).scalars().all()
    signal_dicts = [
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
        for row in signals
    ]
    definitions = load_definitions("config/behavior_definitions.d")
    evaluations: list[BehaviorEvaluationOut] = []
    for definition in definitions:
        if not definition.enabled:
            continue
        matched_inputs: dict[str, dict] = {}
        for item in definition.inputs:
            metric_signals = [
                signal for signal in signal_dicts
                if signal.get("metric_name") == item.metric_name
                and (not item.analyzers or signal.get("analyzer_id") in item.analyzers)
            ]
            if metric_signals:
                matched_inputs[item.alias] = extract_facts(metric_signals)[item.metric_name]
        if len(matched_inputs) < len(definition.inputs):
            continue
        facts = {alias: metric_fact for alias, metric_fact in matched_inputs.items()}
        evaluation = build_evaluation(definition, facts, matched_inputs, service, analysis_run_id)
        evaluations.append(
            BehaviorEvaluationOut(
                definition_id=evaluation.definition_id,
                definition_version=evaluation.definition_version,
                title=evaluation.title,
                description=evaluation.description,
                matched=evaluation.matched,
                confidence=evaluation.confidence,
                service=evaluation.service,
                analysis_run_id=evaluation.analysis_run_id,
                facts=evaluation.facts,
                matched_conditions=evaluation.matched_conditions,
                evidence=evaluation.evidence,
                correlation=evaluation.correlation,
            )
        )
    return evaluations
