from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime
from itertools import count
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
import yaml

from backend.app.api.assistant import get_assistant
from backend.app.assistant.service import OperationalIntelligenceAssistant
from backend.app.metric_analyzer_recommendations.schemas import (
    AIAnalyzerOpinionOut,
    AnalyzerDivergenceOut,
    AnalyzerRecommendationChatResponseOut,
    AnalyzerRecommendationRequestIn,
    AnalyzerRecommendationOut,
    MetricContextIn,
    MetricProfileOut,
    MetricSampleOut,
    RecommendationResponseOut,
)
from backend.app.metric_analyzer_recommendations.service import MetricAnalyzerRecommendationService
from backend.app.models.db import get_db
from backend.app.models.entities import AnalyzerDivergenceEntity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/metric-analyzer-recommendations", tags=["metric-analyzer-recommendations"])
service = MetricAnalyzerRecommendationService()
_analyzer_config = yaml.safe_load(Path("config/analyzers.yaml").read_text()) if Path("config/analyzers.yaml").exists() else {}
_conversation_counter = count(1)
_evaluation_counter = count(1)
_conversation_store: dict[str, dict[str, Any]] = {}
_latest_evaluation_by_conversation: dict[str, dict[str, Any]] = {}


@router.get("/metrics")
def list_metric_samples(db: Session = Depends(get_db)) -> list[MetricSampleOut]:
    return [MetricSampleOut(**sample) for sample in service.list_samples(db)]


def _record_ai_divergence(
    db: Session,
    *,
    service_name: str | None,
    metric_name: str,
    analysis_run_id: str | None,
    ai_opinion: AIAnalyzerOpinionOut,
    recommendations: list[AnalyzerRecommendationOut],
) -> None:
    """Best-effort log of the AI second opinion's pick alongside the router's, recorded whether or
    not they agreed - the denominator matters as much as the divergences do for computing a real
    divergence rate later. When analysis_run_id is present, this can be joined against
    analyzer_learning_outcomes on the same column to check whether the AI's pick or the router's
    pick actually matched the eventual confirmed/rejected outcome. Never raises - a failure here
    must never affect the recommendation response itself."""
    if not ai_opinion.available or not ai_opinion.best_analyzer_id or not ai_opinion.router_top_analyzer_id:
        return
    try:
        router_top_score = next(
            (item.fitness_score for item in recommendations if item.analyzer_id == ai_opinion.router_top_analyzer_id),
            None,
        )
        ai_confidence = next(
            (pick.confidence for pick in ai_opinion.recommended if pick.analyzer_id == ai_opinion.best_analyzer_id),
            None,
        )
        db.add(
            AnalyzerDivergenceEntity(
                id=uuid4().hex,
                service=service_name,
                metric_name=metric_name,
                analysis_run_id=analysis_run_id,
                router_top_analyzer_id=ai_opinion.router_top_analyzer_id,
                router_top_score=router_top_score,
                ai_top_analyzer_id=ai_opinion.best_analyzer_id,
                ai_confidence=ai_confidence,
                diverged=ai_opinion.diverges_from_router,
                created_at=datetime.utcnow(),
            )
        )
        db.commit()
    except Exception as exc:
        logger.warning(f"Failed to record AI-divergence tracking row: {exc}")
        db.rollback()


@router.get("/divergences", response_model=list[AnalyzerDivergenceOut])
def list_ai_divergences(
    metric_name: str | None = None,
    service: str | None = None,
    diverged: bool | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[AnalyzerDivergenceOut]:
    """Raw log of AI-vs-router evaluations, for auditing whether the deterministic scoring rules
    are calibrated well. Correlating a row against its real outcome is a join on analysis_run_id
    against /api/learning-outcomes - not built as a canned aggregate here, to keep this endpoint
    to what it actually is: the log, not a report."""
    query = select(AnalyzerDivergenceEntity)
    if metric_name:
        query = query.where(AnalyzerDivergenceEntity.metric_name == metric_name)
    if service:
        query = query.where(AnalyzerDivergenceEntity.service == service)
    if diverged is not None:
        query = query.where(AnalyzerDivergenceEntity.diverged == diverged)
    query = query.order_by(AnalyzerDivergenceEntity.created_at.desc()).limit(max(1, min(limit, 500)))
    rows = db.execute(query).scalars().all()
    return [
        AnalyzerDivergenceOut(
            id=row.id,
            service=row.service,
            metric_name=row.metric_name,
            analysis_run_id=row.analysis_run_id,
            router_top_analyzer_id=row.router_top_analyzer_id,
            router_top_score=row.router_top_score,
            ai_top_analyzer_id=row.ai_top_analyzer_id,
            ai_confidence=row.ai_confidence,
            diverged=row.diverged,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("/evaluate", response_model=RecommendationResponseOut)
def evaluate_metric_sample(
    payload: dict,
    db: Session = Depends(get_db),
    assistant: OperationalIntelligenceAssistant | None = Depends(get_assistant),
) -> RecommendationResponseOut:
    service_name = str(payload.get("service", "")).strip()
    metric_name = str(payload.get("metric_name", "")).strip()
    analysis_run_id = payload.get("analysis_run_id")
    if analysis_run_id is not None:
        analysis_run_id = str(analysis_run_id).strip() or None
    if not service_name or not metric_name:
        raise HTTPException(status_code=400, detail="service and metric_name are required")
    selected = service.find_sample(db, service_name, metric_name, analysis_run_id)
    if not selected:
        raise HTTPException(status_code=404, detail="sample not found")
    analysis_run_id = selected["analysis_run_id"]
    try:
        profile, timeseries = service.profile_sample(db, service_name, metric_name, analysis_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    analysis_config = _analyzer_config.get("analysis", {}) if isinstance(_analyzer_config, dict) else {}
    selection_mode = str(analysis_config.get("recommendation_selection_mode", "all"))
    selected_analyzers = list(analysis_config.get("selected_analyzers", []) or [])
    recommendations = [AnalyzerRecommendationOut(**item) for item in service.recommend(profile, selection_mode, selected_analyzers, timeseries)]
    ai_services = assistant.services.ai_services if assistant else None
    ai_opinion = AIAnalyzerOpinionOut(
        **service.recommend_ai_opinion(profile, timeseries, ai_services, metric_context={"service": service_name, "metric_name": metric_name})
    )
    _record_ai_divergence(
        db,
        service_name=service_name,
        metric_name=metric_name,
        analysis_run_id=analysis_run_id,
        ai_opinion=ai_opinion,
        recommendations=recommendations,
    )
    return RecommendationResponseOut(
        sample=MetricSampleOut(**selected),
        profile=MetricProfileOut(**asdict(profile)),
        recommendations=recommendations,
        ai_opinion=ai_opinion,
    )


@router.post("/chat", response_model=AnalyzerRecommendationChatResponseOut)
def chat_metric_analyzer_recommendation(
    payload: AnalyzerRecommendationRequestIn,
    db: Session = Depends(get_db),
    assistant: OperationalIntelligenceAssistant | None = Depends(get_assistant),
) -> AnalyzerRecommendationChatResponseOut:
    conversation_id = payload.conversation_id or f"conversation-{next(_conversation_counter)}"
    context = payload.metric_context
    normalized_goals = service.normalize_goals([context.operational_purpose, *context.use_cases, *context.operational_questions, payload.message])
    context_payload = context.model_dump()
    context_hash = service.context_hash(context_payload)
    previous = _latest_evaluation_by_conversation.get(conversation_id)
    stale = bool(previous and previous.get("context_hash") != context_hash)

    sample = None
    profile = None
    timeseries: list[tuple[Any, float]] = []
    recommendations: list[AnalyzerRecommendationOut] = []
    recommendation_mode: str = "preliminary"
    evaluation_id: int | None = None
    analysis_config = _analyzer_config.get("analysis", {}) if isinstance(_analyzer_config, dict) else {}
    selection_mode = str(analysis_config.get("recommendation_selection_mode", "all"))
    selected_analyzers = list(analysis_config.get("selected_analyzers", []) or [])

    if context.sample_id is not None or (context.metric_name and context.provider):
        try:
            sample = service.find_metric_sample(db, context.metric_name, context.provider) if context.metric_name else None
            if context.sample_id is not None and sample is not None:
                profile, timeseries = service.profile_sample(db, sample["service"], sample["metric_name"], sample.get("analysis_run_id"))
                recommendations = [AnalyzerRecommendationOut(**item) for item in service.recommend(profile, selection_mode, selected_analyzers, timeseries)]
                recommendation_mode = "evaluated"
                evaluation_id = next(_evaluation_counter)
        except Exception:
            sample = None

    if sample is None:
        recommendations = [AnalyzerRecommendationOut(**item) for item in service.recommend(_preliminary_profile(context), selection_mode, selected_analyzers)]
        recommendation_mode = "preliminary"

    if recommendation_mode == "evaluated" and profile is not None:
        ai_services = assistant.services.ai_services if assistant else None
        ai_opinion = AIAnalyzerOpinionOut(
            **service.recommend_ai_opinion(
                profile, timeseries, ai_services, metric_context={"metric_name": context.metric_name, "operational_purpose": context.operational_purpose}
            )
        )
        _record_ai_divergence(
            db,
            service_name=sample.get("service") if sample else None,
            metric_name=context.metric_name,
            analysis_run_id=sample.get("analysis_run_id") if sample else None,
            ai_opinion=ai_opinion,
            recommendations=recommendations,
        )
    else:
        ai_opinion = AIAnalyzerOpinionOut(available=False, unavailable_reason="No historical sample evaluated yet")

    assistant_message = {
        "headline": _headline_for(recommendations, recommendation_mode),
        "summary": _summary_for(context, recommendations, recommendation_mode),
        "context_used": _context_used(context, recommendation_mode),
        "next_action": "Review the evidence or upload a representative sample." if recommendation_mode == "preliminary" else "Review the evidence or save this sample as a benchmark.",
    }

    response = AnalyzerRecommendationChatResponseOut(
        conversation_id=conversation_id,
        evaluation_id=evaluation_id,
        response_type="analyzer_recommendation",
        recommendation_mode=recommendation_mode,  # type: ignore[arg-type]
        assistant_message=assistant_message,
        recommendations=recommendations,
        suggested_questions=[
            "Why was STUMPY rejected?",
            "What preprocessing is required?",
            "Compare Trend and Ruptures.",
            "Save this sample as a benchmark.",
        ],
        context_hash=context_hash,
        context_version=1,
        ai_opinion=ai_opinion,
        normalized_goals=[_to_goal_out(goal) for goal in normalized_goals],
        stale=stale,
    )
    _conversation_store[conversation_id] = {"payload": payload.model_dump(), "updated_at": datetime.utcnow().isoformat()}
    _latest_evaluation_by_conversation[conversation_id] = {"context_hash": context_hash, "evaluation_id": evaluation_id}
    return response


def _preliminary_profile(context: MetricContextIn):
    return type(
        "PreliminaryProfile",
        (),
        {
            "sample_count": max(len(context.example_values), 1),
            "trend_strength": 0.4,
            "metric_behavior": (context.metric_type or "unknown").lower(),
            "regular_sampling": False,
            "seasonality_strength": 0.2,
            "constant_value_ratio": 0.0,
            "missing_ratio": 0.0,
            "variance": 1.0,
            "stddev": 1.0,
            "mean": 1.0,
            "minimum": 0.0,
            "maximum": 1.0,
            "trend_slope": 0.0,
            "autocorrelation": None,
            "start_time": datetime.utcnow(),
            "end_time": datetime.utcnow(),
            "duplicate_timestamps": 0,
            "sparsity": 0.0,
        },
    )()


def _headline_for(recommendations: list[AnalyzerRecommendationOut], mode: str) -> str:
    names = [item.display_name for item in recommendations if item.recommendation == "recommended"][:2]
    if mode == "preliminary":
        return "Preliminary recommendation based on metric context."
    return f"{' and '.join(names) if names else 'Analyzer recommendations'} are the strongest matches for this metric."


def _summary_for(context: MetricContextIn, recommendations: list[AnalyzerRecommendationOut], mode: str) -> str:
    if mode == "preliminary":
        return "This recommendation is based on metric context and operational goals. Select or upload a representative historical sample to verify analyzer fitness and calculate evidence-based confidence."
    top = next((item for item in recommendations if item.recommendation == "recommended"), None)
    if top:
        return f"{context.metric_name} is most aligned with {top.display_name.lower()} given the operational purpose and sample evidence."
    return f"{context.metric_name} has a mixed recommendation profile."


def _context_used(context: MetricContextIn, mode: str) -> list[str]:
    items = [context.metric_name, context.metric_description, context.operational_purpose, *context.use_cases, *context.operational_questions]
    if mode == "preliminary":
        items.append("No historical sample")
    elif context.sample_id is not None:
        items.append("Historical sample")
    return [item for item in items if item]


def _to_goal_out(goal: dict[str, str]):
    return goal
