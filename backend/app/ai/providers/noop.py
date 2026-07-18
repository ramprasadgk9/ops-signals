"""No-op provider used when AI is disabled."""

from __future__ import annotations

from backend.app.ai.exceptions import LLMDisabledError
from backend.app.ai.interfaces import LLMClient, LLMRequest, LLMResponse


class NoOpLLMClient(LLMClient):
    def generate(self, request: LLMRequest) -> LLMResponse:
        raise LLMDisabledError("AI is disabled for this deployment")
