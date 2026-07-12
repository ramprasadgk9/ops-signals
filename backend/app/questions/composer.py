from __future__ import annotations

from backend.app.questions.handlers.behavior_novelty import compose_behavior_novelty
from backend.app.questions.handlers.baseline_changes import compose_baseline_changes
from backend.app.questions.handlers.investigation_priority import compose_investigation_priority
from backend.app.questions.handlers.long_term_trends import compose_long_term_trends
from backend.app.questions.handlers.service_health import compose_service_health
from backend.app.questions.handlers.unusual_activity import compose_unusual_activity
from backend.app.questions.handlers.what_changed import compose_what_changed
from backend.app.questions.schema import QuestionAnswerResponse


class AnswerComposer:
    def compose(self, question_id: str, signals: list[dict]) -> QuestionAnswerResponse:
        if question_id == "what_changed":
            return compose_what_changed(question_id, signals)
        if question_id == "investigation_priority":
            return compose_investigation_priority(question_id, signals)
        if question_id == "unusual_activity":
            return compose_unusual_activity(question_id, signals)
        if question_id == "behavior_novelty":
            return compose_behavior_novelty(question_id, signals)
        if question_id == "baseline_changes":
            return compose_baseline_changes(question_id, signals)
        if question_id == "long_term_trends":
            return compose_long_term_trends(question_id, signals)
        if question_id == "service_health":
            return compose_service_health(question_id, signals)
        if question_id == "historical_similarity":
            return QuestionAnswerResponse(
                question_id=question_id,
                headline="Historical similarity search is not enabled yet.",
                answer="This capability is planned and will be available after similarity indexing is implemented.",
                status="not_supported",
                priority="low",
                confidence=1.0,
                key_points=["Historical similarity is not yet implemented in version 1."],
                evidence_signal_ids=[],
            )
        return QuestionAnswerResponse(
            question_id=question_id,
            headline="Unsupported question.",
            answer="No deterministic composer is defined for this question id.",
            status="unknown",
            priority="low",
            confidence=0.0,
            key_points=[],
            evidence_signal_ids=[],
        )
