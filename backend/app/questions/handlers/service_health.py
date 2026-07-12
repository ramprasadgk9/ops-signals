from __future__ import annotations

from backend.app.questions.handlers.common import summarize_signals
from backend.app.questions.schema import QuestionAnswerResponse


def compose_service_health(question_id: str, signals: list[dict]) -> QuestionAnswerResponse:
    summary = summarize_signals(signals)
    high = summary["severities"].get("high", 0)
    medium = summary["severities"].get("medium", 0)
    score = max(0, 100 - (high * 25 + medium * 10))
    if score >= 80:
        status = "healthy"
        priority = "low"
    elif score >= 60:
        status = "watch"
        priority = "medium"
    else:
        status = "needs_attention"
        priority = "high"
    points = [
        f"Health score: {score}/100",
        f"High severity signals: {high}",
        f"Medium severity signals: {medium}",
    ]
    return QuestionAnswerResponse(
        question_id=question_id,
        headline="Service health summary generated.",
        answer="; ".join(points),
        status=status,
        priority=priority,
        confidence=max(summary["avg_conf"], 0.75 if signals else 0.9),
        key_points=points,
        evidence_signal_ids=summary["signal_ids"][:5],
    )
