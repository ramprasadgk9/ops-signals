from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from itertools import count
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.metric_analyzer_recommendations.schemas import (
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

router = APIRouter(prefix="/api/metric-analyzer-recommendations", tags=["metric-analyzer-recommendations"])
service = MetricAnalyzerRecommendationService()
_conversation_counter = count(1)
_evaluation_counter = count(1)
_conversation_store: dict[str, dict[str, Any]] = {}
_latest_evaluation_by_conversation: dict[str, dict[str, Any]] = {}


@router.get("/metrics")
def list_metric_samples(db: Session = Depends(get_db)) -> list[MetricSampleOut]:
    return [MetricSampleOut(**sample) for sample in service.list_samples(db)]


@router.post("/evaluate", response_model=RecommendationResponseOut)
def evaluate_metric_sample(
    payload: dict,
    db: Session = Depends(get_db),
) -> RecommendationResponseOut:
    service_name = str(payload.get("service", "")).strip()
    metric_name = str(payload.get("metric_name", "")).strip()
    analysis_run_id = payload.get("analysis_run_id")
    if analysis_run_id is not None:
        analysis_run_id = str(analysis_run_id).strip() or None
    if not service_name or not metric_name:
        raise HTTPException(status_code=400, detail="service and metric_name are required")
    try:
        profile, _ = service.profile_sample(db, service_name, metric_name, analysis_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    sample = service.list_samples(db)
    selected = next(
        (item for item in sample if item["service"] == service_name and item["metric_name"] == metric_name and item["analysis_run_id"] == analysis_run_id),
        None,
    )
    if not selected:
        raise HTTPException(status_code=404, detail="sample not found")

    recommendations = [AnalyzerRecommendationOut(**item) for item in service.recommend(profile)]
    return RecommendationResponseOut(
        sample=MetricSampleOut(**selected),
        profile=MetricProfileOut(**asdict(profile)),
        recommendations=recommendations,
    )


@router.post("/chat", response_model=AnalyzerRecommendationChatResponseOut)
def chat_metric_analyzer_recommendation(
    payload: AnalyzerRecommendationRequestIn,
    db: Session = Depends(get_db),
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
    recommendations: list[AnalyzerRecommendationOut] = []
    recommendation_mode: str = "preliminary"
    evaluation_id: int | None = None

    if context.sample_id is not None or (context.metric_name and context.provider):
        try:
            sample_rows = service.list_samples(db)
            sample = next(
                (
                    item
                    for item in sample_rows
                    if item["metric_name"] == context.metric_name
                    and (context.provider is None or item["service"] == context.provider or context.provider.lower() in item["service"].lower())
                ),
                None,
            )
            if context.sample_id is not None and sample is not None:
                profile, _ = service.profile_sample(db, sample["service"], sample["metric_name"], sample.get("analysis_run_id"))
                recommendations = [AnalyzerRecommendationOut(**item) for item in service.recommend(profile)]
                recommendation_mode = "evaluated"
                evaluation_id = next(_evaluation_counter)
        except Exception:
            sample = None

    if sample is None:
        recommendations = [AnalyzerRecommendationOut(**item) for item in service.recommend(_preliminary_profile(context))]
        recommendation_mode = "preliminary"

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
            "trend_slope": 0.0,
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
