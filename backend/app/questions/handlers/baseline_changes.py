from __future__ import annotations

from backend.app.questions.schema import QuestionAnswerResponse


def compose_baseline_changes(question_id: str, signals: list[dict]) -> QuestionAnswerResponse:
    baseline = [sig for sig in signals if sig.get("signal_type") == "baseline_shift"]
    if not baseline:
        return QuestionAnswerResponse(
            question_id=question_id,
            headline="No baseline changes detected.",
            answer="The operating baseline remained within configured thresholds.",
            status="healthy",
            priority="low",
            confidence=0.9,
            key_points=["No baseline shift signals were found."],
            evidence_signal_ids=[],
        )
    top = sorted(baseline, key=lambda x: float(x.get("importance_score") or 0), reverse=True)[0]
    evidence = top.get("evidence") or {}
    before = evidence.get("first_half_mean")
    after = evidence.get("second_half_mean")
    change = evidence.get("percent_change")
    points = [f"Baseline changed by {change:.1f}%" if isinstance(change, (int, float)) else "Baseline changed"]
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        points.append(f"Before mean {before:.2f}, after mean {after:.2f}")
    return QuestionAnswerResponse(
        question_id=question_id,
        headline="Baseline changes were detected.",
        answer="; ".join(points),
        status="needs_attention",
        priority="high" if top.get("severity") == "high" else "medium",
        confidence=float(top.get("confidence") or 0.7),
        key_points=points,
        evidence_signal_ids=[str(sig.get("id")) for sig in baseline[:5]],
    )
