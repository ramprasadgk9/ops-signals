from __future__ import annotations

from backend.app.questions.handlers.common import summarize_signals
from backend.app.questions.schema import QuestionAnswerResponse


def compose_investigation_priority(question_id: str, signals: list[dict]) -> QuestionAnswerResponse:
    summary = summarize_signals(signals)
    top = summary["top"][:3]
    if not top:
        return QuestionAnswerResponse(
            question_id=question_id,
            headline="No urgent findings right now.",
            answer="No high-importance signals are available for this analysis run.",
            status="healthy",
            priority="low",
            confidence=0.9,
            key_points=["No prioritized findings were generated."],
            evidence_signal_ids=[],
        )
    key_points = [
        f"{sig.get('signal_type', 'signal')} - importance {float(sig.get('importance_score') or 0):.2f}"
        for sig in top
    ]
    return QuestionAnswerResponse(
        question_id=question_id,
        headline="Prioritized investigation list is ready.",
        answer="Start with the highest importance signals and work downward.",
        status="needs_attention",
        priority="high",
        confidence=max(summary["avg_conf"], 0.75),
        key_points=key_points,
        evidence_signal_ids=[str(sig.get("id")) for sig in top],
    )
