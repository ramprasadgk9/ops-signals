"""Anthropic (Claude) provider adapter, using the official Anthropic SDK."""

from __future__ import annotations

import time
from typing import Any, Sequence

try:
    import anthropic
except ImportError:  # optional: only needed when provider is "anthropic"
    anthropic = None  # type: ignore[assignment]

from backend.app.ai.exceptions import LLMRequestError
from backend.app.ai.interfaces import LLMClient, LLMRequest, LLMResponse
from backend.app.ai.tool_calls import ToolCall, ToolRequest, ToolResponse, ToolTurn, parse_arguments

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

    def generate_with_tools(self, request: ToolRequest) -> ToolResponse:
        """One turn of a tool conversation. The assistant's content blocks go back unchanged on the
        next request (raw), thinking blocks included, as the API requires; every tool result of a
        turn goes back in one user message."""
        start = time.perf_counter()
        system = "\n\n".join(turn.content for turn in request.messages if turn.role == "system")
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_tokens + THINKING_HEADROOM_TOKENS if request.max_tokens else DEFAULT_MAX_TOKENS,
            "messages": _tool_messages(request.messages),
            "tools": [{"name": tool.name, "description": tool.description, "input_schema": tool.parameters} for tool in request.tools],
        }
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
        calls = tuple(
            ToolCall(id=block.id, name=block.name, arguments=parse_arguments(block.input))
            for block in response.content
            if block.type == "tool_use"
        )
        content = "".join(block.text for block in response.content if block.type == "text").strip()
        if not content and not calls:
            if response.stop_reason == "max_tokens":
                raise LLMRequestError("Anthropic ran out of tokens before writing an answer (max_tokens reached while thinking)")
            raise LLMRequestError("Anthropic returned an empty response")
        usage = getattr(response, "usage", None)
        return ToolResponse(
            content=content,
            tool_calls=calls,
            raw=[_block_dict(block) for block in response.content],
            model=getattr(response, "model", None) or self.model,
            provider="anthropic",
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
        )


def _tool_messages(turns: Sequence[ToolTurn]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    def flush_results() -> None:
        if results:
            messages.append({"role": "user", "content": list(results)})
            results.clear()

    for turn in turns:
        if turn.role == "system":
            continue
        if turn.role == "tool":
            result: dict[str, Any] = {"type": "tool_result", "tool_use_id": turn.tool_call_id, "content": turn.content}
            if turn.is_error:
                result["is_error"] = True
            results.append(result)
            continue
        flush_results()
        if turn.role == "assistant":
            if turn.raw is not None and turn.provider == "anthropic":
                messages.append({"role": "assistant", "content": turn.raw})
                continue
            blocks: list[dict[str, Any]] = [{"type": "text", "text": turn.content}] if turn.content else []
            blocks += [{"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments} for call in turn.tool_calls]
            messages.append({"role": "assistant", "content": blocks or turn.content})
            continue
        messages.append({"role": "user", "content": turn.content})
    flush_results()
    return messages


def _block_dict(block: Any) -> dict[str, Any]:
    """A response block as the API sent it, to send back unchanged."""
    to_dict = getattr(block, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    model_dump = getattr(block, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json", exclude_unset=True)
    return {key: value for key, value in vars(block).items() if not key.startswith("_")}
