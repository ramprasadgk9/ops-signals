"""AI-backed relevance evaluator for external ticketing comments.

During active incidents, external tickets (e.g. Jira) receive comments ranging from
critical operational clues (remediation steps, root cause observations, diagnostic telemetry)
to administrative noise (sprint changes, user mentions, scheduling). This service evaluates
unpromoted comments against case context to determine whether they meet the threshold
to be auto-promoted into the case investigation notes.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from backend.app.ai.exceptions import AIError
from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.interfaces import LLMMessage, LLMRequest

logger = logging.getLogger(__name__)


class CommentTriageEvaluation(BaseModel):
    """Pydantic schema for structured comment triage evaluation."""

    is_relevant_clue: bool = Field(
        ...,
        description=(
            "Whether this comment contains an operational clue, diagnosis, root cause hypothesis, "
            "or remediation action relevant to the incident under investigation."
        ),
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0 indicating certainty of relevance.",
    )
    reason: str = Field(
        ...,
        description="Concise rationale explaining why the comment was classified as relevant or not.",
    )


class CommentTriageService:
    """Evaluates external ticket comments for operational relevance using structured LLM output."""

    TRIAGE_SYSTEM_PROMPT = (
        "You are an expert site reliability engineer and operational intelligence assistant.\n"
        "Your task is to evaluate an external ticket comment posted during an active service incident "
        "and determine whether it contains substantive operational clues, root cause observations, "
        "diagnostic findings, or remediation actions.\n\n"
        "EVALUATION CRITERIA:\n"
        "1. Mark `is_relevant_clue = true` (confidence >= 0.75) ONLY if the comment contains concrete operational information, such as:\n"
        "   - Diagnostic discoveries (e.g. database deadlocks, connection exhaustion, CPU saturation, network drops)\n"
        "   - Mitigation or remediation actions taken (e.g. pods restarted, service rolled back, cache flushed, pool resized)\n"
        "   - Telemetry observations directly related to the service or metric under investigation\n"
        "2. Mark `is_relevant_clue = false` (or confidence < 0.75) if the comment is:\n"
        "   - Administrative or project management chatter (e.g. 'moving to sprint 12', 'assigning to @alice', 'ccing lead')\n"
        "   - Trivial status acknowledgments without diagnostic details (e.g. 'looking into this', 'will check soon', 'ack', 'thanks')\n"
        "   - General discussion not providing actionable incident clues\n"
        "3. Output MUST be valid JSON adhering strictly to the CommentTriageEvaluation schema."
    )

    def __init__(self, confidence_threshold: float = 0.75) -> None:
        self.confidence_threshold = confidence_threshold

    def evaluate(
        self,
        ai_services: OptionalAIServices | None,
        *,
        case_context: dict[str, Any],
        author: str | None,
        comment_body: str,
        timeout_seconds: float = 15.0,
    ) -> CommentTriageEvaluation | None:
        """Evaluates an external ticket comment against case context.

        Returns None if AI services are unavailable, comment text is empty, or evaluation fails.
        Never raises - callers treat None as unpromoted (graceful deterministic fallback).
        """
        if not ai_services or not comment_body.strip():
            return None

        user_content = (
            f"INCIDENT CASE CONTEXT:\n"
            f"- Title: {case_context.get('case_title', 'Incident')}\n"
            f"- Service: {case_context.get('service', 'Unknown')}\n"
            f"- Metric: {case_context.get('metric_name', 'Unknown')}\n"
            f"- Finding Summary: {case_context.get('summary', '')}\n\n"
            f"EXTERNAL TICKET COMMENT:\n"
            f"- Author: {author or 'Unknown'}\n"
            f"- Comment: {comment_body.strip()}\n"
        )

        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content=self.TRIAGE_SYSTEM_PROMPT),
                LLMMessage(role="user", content=user_content),
            ],
            temperature=0.0,
            max_tokens=200,
            response_format="json",
            timeout_seconds=timeout_seconds,
        )

        try:
            return ai_services.structured.generate_structured(request, CommentTriageEvaluation)
        except AIError as exc:
            logger.warning(
                "Comment triage AI evaluation failed, falling back to manual: %s",
                exc,
            )
            return None

    def is_promotable(self, evaluation: CommentTriageEvaluation | None) -> bool:
        """Determines if an evaluation result warrants automated promotion into case notes."""
        if not evaluation:
            return False
        return evaluation.is_relevant_clue and evaluation.confidence >= self.confidence_threshold
