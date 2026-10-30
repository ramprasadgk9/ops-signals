from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Text, cast, or_, select
from sqlalchemy.orm import Session

from backend.app.ai.services.narrative_service import synthesize_narrative
from backend.app.api.assistant import get_assistant
from backend.app.assistant.service import OperationalIntelligenceAssistant
from backend.app.behavior_intelligence.condition_evaluator import evaluate_conditions
from backend.app.behavior_intelligence.confidence import calculate_confidence
from backend.app.behavior_intelligence.fact_extractor import extract_facts
from backend.app.behavior_intelligence.finding_builder import build_evaluation
from backend.app.behavior_intelligence.loader import load_definitions
from backend.app.behavior_intelligence.schemas import BehaviorEvaluationOut, BehaviorFindingOut, run_ids_of
from backend.app.behavior_intelligence.service import BehaviorIntelligenceService
from backend.app.models.db import get_db
from backend.app.models.entities import BehaviorFindingEntity, SignalEntity

router = APIRouter(prefix="/api/behavior-evaluations", tags=["behavior-evaluations"])

# Writing an explanation takes seconds with a local model, and the list waited for every new one:
# the Findings page took over 30 s to load the first time with four patterns. New explanations stop
# after this long; the rest are written on later loads (one already written costs nothing).
AI_EXPLANATION_BUDGET_SECONDS = 5.0


def _service() -> BehaviorIntelligenceService:
    return BehaviorIntelligenceService("config/behavior_definitions.d")


def _ensure_ai_explanation(finding: BehaviorFindingEntity, db: Session, assistant: OperationalIntelligenceAssistant | None) -> None:
    """Best-effort, cached plain-English rewrite of the structured facts/conditions that already
    explain why this behavior matched. Additive only - `summary`, `facts_json`, and
    `matched_conditions_json` stay exactly as they've always been; a missing AI service or any
    failure here just leaves `ai_explanation` as None."""
    if finding.ai_explanation or not assistant or not assistant.services.ai_services:
        return
    evidence_text = (
        f"Title: {finding.title}\n"
        f"Summary: {finding.summary}\n"
        f"Category: {finding.category}\n"
        f"Severity: {finding.severity}\n"
        f"Confidence: {finding.confidence}\n"
        f"Matched facts: {finding.facts_json or {}}\n"
        f"Matched conditions: {finding.matched_conditions_json or []}\n"
        f"Correlation: {finding.correlation_json or {}}"
    )
    try:
        explanation = synthesize_narrative(
            assistant.services.ai_services,
            instruction=(
                "Explain in 1-3 plain-language sentences why this cross-metric behavior finding matched, "
                "for an on-call engineer, using ONLY the facts and conditions given - do not invent metrics, "
                "numbers, or causes not present in the evidence."
            ),
            evidence_text=evidence_text,
            max_tokens=150,
        )
    except Exception:
        return
    if not explanation:
        return
    finding.ai_explanation = explanation
    db.commit()


@router.get("", response_model=list[BehaviorFindingOut])
def list_behavior_findings(
    definition_id: str | None = None,
    service: str | None = None,
    analysis_run_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    assistant: OperationalIntelligenceAssistant | None = Depends(get_assistant),
) -> list[BehaviorFindingOut]:
    query = select(BehaviorFindingEntity)
    if definition_id:
        query = query.where(BehaviorFindingEntity.definition_id == definition_id)
    if service:
        query = query.where(BehaviorFindingEntity.service == service)
    if analysis_run_id:
        query = query.where(
            or_(
                BehaviorFindingEntity.analysis_run_id == analysis_run_id,
                cast(BehaviorFindingEntity.correlation_json, Text).contains(analysis_run_id),
            )
        )
    rows = db.execute(query.order_by(BehaviorFindingEntity.created_at.desc())).scalars().all()
    if analysis_run_id:
        # A match from a scheduled analysis spans one run per metric (BehaviorFindingOut.analysis_run_ids).
        rows = [row for row in rows if analysis_run_id in run_ids_of(row.analysis_run_id, row.correlation_json)]
    deadline = time.monotonic() + AI_EXPLANATION_BUDGET_SECONDS
    for row in rows:
        if time.monotonic() >= deadline:
            break
        _ensure_ai_explanation(row, db, assistant)
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
