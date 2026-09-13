"""Shared LLM narrative-synthesis primitive.

Every AI-polish feature in this app (assistant answers, finding summaries, behavior explanations,
case RCA/resolution drafts) follows the same rule: ask a configured model to write text grounded
ONLY in supplied evidence, and treat a None return as "AI is unavailable or failed - use your own
deterministic fallback." This module is that one call site, so each feature doesn't hand-roll its
own LLMRequest construction and AIError handling.
"""

from __future__ import annotations

import logging

from backend.app.ai.exceptions import AIError
from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.interfaces import LLMMessage, LLMRequest

logger = logging.getLogger(__name__)


def synthesize_narrative(
    ai_services: OptionalAIServices | None,
    *,
    instruction: str,
    evidence_text: str,
    max_tokens: int = 200,
    temperature: float = 0.1,
    timeout_seconds: float = 15,
) -> str | None:
    """Returns None when AI is unavailable, there's no evidence to ground the answer in, or the
    call fails. Never raises - callers must always have their own deterministic fallback ready."""
    if not ai_services or not evidence_text.strip():
        return None
    request = LLMRequest(
        messages=[
            LLMMessage(role="system", content=instruction),
            LLMMessage(role="user", content=evidence_text),
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        response_format="text",
        timeout_seconds=timeout_seconds,
    )
    try:
        response = ai_services.client.generate(request)
    except AIError as exc:
        logger.warning("LLM narrative synthesis failed, caller will use its deterministic fallback: %s", exc)
        return None
    content = response.content.strip()
    return content or None
