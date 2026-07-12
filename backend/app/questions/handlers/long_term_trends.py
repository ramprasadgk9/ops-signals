from __future__ import annotations

from backend.app.questions.schema import QuestionAnswerResponse


def compose_long_term_trends(question_id: str, signals: list[dict]) -> QuestionAnswerResponse:
    trend_signals = [sig for sig in signals if sig.get("signal_type") == "trend"]
    if not trend_signals:
        return QuestionAnswerResponse(
            question_id=question_id,
            headline="No strong long-term trend detected.",
            answer="The metric remained broadly stable in the selected window.",
            status="healthy",
            priority="low",
            confidence=0.88,
            key_points=["No trend signal exceeded the configured threshold."],
            evidence_signal_ids=[],
        )
    top = sorted(trend_signals, key=lambda x: float(x.get("importance_score") or 0), reverse=True)[0]
    evidence = top.get("evidence") or {}
    slope_pct = evidence.get("slope_percent")
    direction = "upward" if float(slope_pct or 0) > 0 else "downward"
    points = [f"Sustained {direction} trend detected"]
    if isinstance(slope_pct, (int, float)):
        points.append(f"Change across window: {slope_pct:.1f}%")
    return QuestionAnswerResponse(
        question_id=question_id,
        headline="Long-term trend signal detected.",
        answer="; ".join(points),
        status="needs_attention",
        priority="high" if top.get("severity") == "high" else "medium",
        confidence=float(top.get("confidence") or 0.7),
        key_points=points,
        evidence_signal_ids=[str(sig.get("id")) for sig in trend_signals[:5]],
    )
