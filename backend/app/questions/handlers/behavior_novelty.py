from __future__ import annotations

from backend.app.questions.handlers.common import summarize_signals
from backend.app.questions.schema import QuestionAnswerResponse


def compose_behavior_novelty(question_id: str, signals: list[dict]) -> QuestionAnswerResponse:
    baseline_or_trend = [sig for sig in signals if sig.get("signal_type") in {"baseline_shift", "ruptures", "trend"}]
    summary = summarize_signals(baseline_or_trend)
    if not baseline_or_trend:
        return QuestionAnswerResponse(
            question_id=question_id,
            headline="Behavior looks expected.",
            answer="No material baseline or directional novelty was detected.",
            status="healthy",
            priority="low",
            confidence=0.85,
            key_points=["No strong novelty signals were generated."],
            evidence_signal_ids=[],
        )
    points = ["Current behavior differs from the previous window."]
    if summary["counts"].get("baseline_shift"):
        points.append("Baseline level changed")
    if summary["counts"].get("ruptures"):
        points.append("A change point split the time series into different regimes")
    if summary["counts"].get("trend"):
        points.append("Trend direction changed materially")
    return QuestionAnswerResponse(
        question_id=question_id,
        headline="Behavior appears new compared to prior windows.",
        answer="; ".join(points),
        status="needs_attention",
        priority="medium",
        confidence=max(summary["avg_conf"], 0.7),
        key_points=points,
        evidence_signal_ids=summary["signal_ids"][:5],
    )
