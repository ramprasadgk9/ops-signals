"""QA-36: model text that isn't a narrative (a broken JSON fragment, "ok", nothing) is treated like
a failed call, so every AI-polish feature falls back to its deterministic text."""

from __future__ import annotations

import pytest

from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.interfaces import LLMRequest, LLMResponse
from backend.app.ai.services.narrative_service import synthesize_narrative


class _Replies:
    def __init__(self, text: str) -> None:
        self.text = text

    def generate(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(content=self.text)


def _ask(reply: str, **kwargs) -> str | None:
    return synthesize_narrative(OptionalAIServices(client=_Replies(reply), structured=None), instruction="Explain.", evidence_text="cpu up", **kwargs)


@pytest.mark.parametrize(
    "reply",
    [
        '{"analyzers": ["pyod_outlier", oops',
        '{"summary": "CPU rose on checkout after the deploy"}',
        '["CPU rose on checkout after the deploy"]',
        "```json\n{\"summary\": \"CPU rose\"}\n```",
        "ok",
        "{}",
        "   ",
        "",
        "...",
    ],
)
def test_a_reply_that_is_not_a_narrative_counts_as_no_answer(reply) -> None:
    assert _ask(reply) is None


@pytest.mark.parametrize(
    "reply",
    [
        "Checkout latency rose right after the 14:00 deploy, and errors followed two minutes later.",
        "CPU stayed high.",
        'CPU on checkout shifted to a new baseline.\n[1] "CPU moved from normal baseline to sustained high usage."',
        '[1] "CPU moved from normal baseline to sustained high usage."',
    ],
)
def test_a_real_narrative_is_returned_unchanged(reply) -> None:
    assert _ask(reply) == reply


def test_a_caller_that_asks_for_short_lines_can_lower_the_word_minimum() -> None:
    assert _ask("1. Pool", min_words=1) == "1. Pool"
