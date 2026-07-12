from __future__ import annotations

from backend.app.questions.handlers.common import summarize_signals
from backend.app.questions.schema import QuestionAnswerResponse


def compose_unusual_activity(question_id: str, signals: list[dict]) -> QuestionAnswerResponse:
    anomalies = [sig for sig in signals if sig.get("signal_type") == "anomaly"]
    summary = summarize_signals(anomalies)
    if not anomalies:
        return QuestionAnswerResponse(
            question_id=question_id,
            headline="No unusual activity detected.",
            answer="No anomaly windows met detection thresholds in the selected window.",
            status="healthy",
            priority="low",
            confidence=0.9,
            key_points=["No anomaly signals were generated."],
            evidence_signal_ids=[],
        )
    points = [f"{len(anomalies)} anomaly window(s) detected"]
    if summary["severities"].get("high", 0):
        points.append("At least one anomaly has high severity")
    return QuestionAnswerResponse(
        question_id=question_id,
        headline="Unusual activity detected.",
        answer="; ".join(points),
        status="needs_attention",
        priority="high" if summary["severities"].get("high", 0) else "medium",
        confidence=max(summary["avg_conf"], 0.7),
        key_points=points,
        evidence_signal_ids=summary["signal_ids"][:5],
    )
