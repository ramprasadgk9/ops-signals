"""Shared LLM narrative-synthesis primitive.

Every AI-polish feature in this app (assistant answers, finding summaries, behavior explanations,
case RCA/resolution drafts) follows the same rule: ask a configured model to write text grounded
ONLY in supplied evidence, and treat a None return as "AI is unavailable or failed - use your own
deterministic fallback." This module is that one call site, so each feature doesn't hand-roll its
own LLMRequest construction and AIError handling.
"""

from __future__ import annotations

import logging
import re

from backend.app.ai.exceptions import AIError
from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.interfaces import LLMMessage, LLMRequest

logger = logging.getLogger(__name__)

_WORD = re.compile(r"[^\W\d_]{2,}")
# A reply that opens like data, not prose: JSON or a code fence. "[1] ..." is a citation line.
_NOT_PROSE = re.compile(r"^(\{|\[(?!\d+\])|```)")


def synthesize_narrative(
    ai_services: OptionalAIServices | None,
    *,
    instruction: str,
    evidence_text: str,
    max_tokens: int = 200,
    temperature: float = 0.1,
    timeout_seconds: float = 15,
    min_words: int = 3,
) -> str | None:
    """Returns None when AI is unavailable, there's no evidence to ground the answer in, the call
    fails, or the reply isn't a narrative (see `_is_narrative`). Never raises - callers must always
    have their own deterministic fallback ready."""
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
    if not _is_narrative(content, min_words):
        logger.warning("LLM reply is not a narrative, caller will use its deterministic fallback: %r", content[:120])
        return None
    return content


def _is_narrative(text: str, min_words: int) -> bool:
    """A model can return successfully with junk: a broken JSON fragment, "ok", punctuation. That
    text used to be shown as the answer or the RCA draft (QA-36); it is now treated like a failed
    call. `min_words` counts words of two or more letters."""
    if not text or _NOT_PROSE.match(text):
        return False
    return len(_WORD.findall(text)) >= min_words
