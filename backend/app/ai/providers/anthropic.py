"""Anthropic (Claude) provider adapter, using the official Anthropic SDK."""

from __future__ import annotations

import time
from typing import Any

try:
    import anthropic
except ImportError:  # optional: only needed when provider is "anthropic"
    anthropic = None  # type: ignore[assignment]

from backend.app.ai.exceptions import LLMRequestError
from backend.app.ai.interfaces import LLMClient, LLMRequest, LLMResponse

DEFAULT_MAX_TOKENS = 16000
# Current Claude models think before they answer, and thinking counts against max_tokens. The
# features ask for budgets sized for the answer alone (8-400 tokens), so add room for the thinking;
# only the tokens actually written are billed.
THINKING_HEADROOM_TOKENS = 8000


class AnthropicLLMClient(LLMClient):
    def __init__(
        self,
        model: str = "claude-opus-5",
        api_key: str | None = None,
        base_url: str | None = None,
        effort: str | None = None,
        timeout_seconds: float = 60.0,
        client: Any | None = None,
    ) -> None:
        self.model = model
        self.effort = effort
        if client is None:
            if anthropic is None:
                raise LLMRequestError("The anthropic package is not installed; run: pip install anthropic")
            client = anthropic.Anthropic(api_key=api_key, base_url=base_url, timeout=timeout_seconds)
        self.client = client

    def generate(self, request: LLMRequest) -> LLMResponse:
        start = time.perf_counter()
        system = "\n\n".join(message.content for message in request.messages if message.role == "system")
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_tokens + THINKING_HEADROOM_TOKENS if request.max_tokens else DEFAULT_MAX_TOKENS,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
                if message.role != "system"
            ],
        }
        # No temperature: current Claude models reject sampling parameters.
        if system:
            kwargs["system"] = system
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        if request.timeout_seconds:
            kwargs["timeout"] = request.timeout_seconds

        try:
            response = self.client.messages.create(**kwargs)
        except Exception as exc:
            if anthropic is not None and isinstance(exc, anthropic.APIError):
                raise LLMRequestError(f"Anthropic request failed: {exc}") from exc
            raise

        if response.stop_reason == "refusal":
            raise LLMRequestError("Anthropic refused the request")
        content = "".join(block.text for block in response.content if block.type == "text").strip()
        if not content:
            if response.stop_reason == "max_tokens":
                raise LLMRequestError("Anthropic ran out of tokens before writing an answer (max_tokens reached while thinking)")
            raise LLMRequestError("Anthropic returned an empty response")
        usage = getattr(response, "usage", None)
        return LLMResponse(
            content=content,
            model=getattr(response, "model", None) or self.model,
            provider="anthropic",
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
        )
