from __future__ import annotations

from backend.app.questions.handlers.common import summarize_signals
from backend.app.questions.schema import QuestionAnswerResponse


def compose_what_changed(question_id: str, signals: list[dict]) -> QuestionAnswerResponse:
    summary = summarize_signals(signals)
    counts = summary["counts"]
    points = []
    if counts.get("baseline_shift"):
        points.append(f"{counts['baseline_shift']} baseline change signal(s) detected")
    if counts.get("ruptures"):
        points.append(f"{counts['ruptures']} change point signal(s) detected")
    if counts.get("trend"):
        points.append(f"{counts['trend']} trend signal(s) detected")
    if counts.get("anomaly"):
        points.append(f"{counts['anomaly']} anomaly window(s) detected")
    if not points:
        points = ["No significant baseline, change point, trend, or anomaly changes were detected."]
    status = "needs_attention" if len(signals) > 0 else "healthy"
    priority = "high" if summary["severities"].get("high", 0) > 0 else "medium"
    return QuestionAnswerResponse(
        question_id=question_id,
        headline="Service behavior changed in the selected window." if signals else "Service behavior remained stable.",
        answer="; ".join(points),
        status=status,
        priority=priority,
        confidence=max(summary["avg_conf"], 0.6 if signals else 0.9),
        key_points=points,
        evidence_signal_ids=summary["signal_ids"][:5],
    )
