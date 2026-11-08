"""Tool calling, the same way for every provider: the model asks for tools, our code runs them.

A provider that can call tools natively has `generate_with_tools` (Anthropic, OpenAI-compatible,
Ollama). Any other client, such as the recorded demo provider, gets the JSON fallback: the tools are
described in the system message and the model answers with one JSON object per turn, either the
calls it wants or its final answer. The fallback is less reliable, since nothing makes the model
keep to the format, so a reply that isn't valid JSON is taken as a final answer.

Our code always runs the loop (backend/app/investigation/loop.py); a provider only turns one
conversation into one reply.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Sequence

from backend.app.ai.interfaces import LLMClient, LLMMessage, LLMRequest


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    # JSON Schema of the arguments.
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolTurn:
    """One message of a tool conversation.

    role: system | user | assistant | tool. An assistant turn may carry `tool_calls`, and `raw`: the
    provider's own reply, sent back unchanged on the next request (Anthropic needs its thinking
    blocks back). A tool turn answers one call by `tool_call_id`.
    """

    role: str
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None
    is_error: bool = False
    raw: Any = None
    provider: str | None = None


@dataclass(frozen=True, slots=True)
class ToolRequest:
    messages: Sequence[ToolTurn]
    tools: Sequence[ToolSpec]
    max_tokens: int | None = None
    timeout_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class ToolResponse:
    """The model's reply: tool calls to run, or (with none) its final answer in `content`."""

    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    raw: Any = None
    model: str | None = None
    provider: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float | None = None

    def as_turn(self) -> ToolTurn:
        return ToolTurn(role="assistant", content=self.content, tool_calls=self.tool_calls, raw=self.raw, provider=self.provider)


def generate_with_tools(client: LLMClient, request: ToolRequest) -> ToolResponse:
    native = getattr(client, "generate_with_tools", None)
    if callable(native):
        return native(request)
    return JsonToolFallback(client).generate_with_tools(request)


def turn_to_dict(turn: ToolTurn) -> dict[str, Any]:
    """A turn as JSON, to save a conversation and continue it later."""
    data: dict[str, Any] = {"role": turn.role, "content": turn.content}
    if turn.tool_calls:
        data["tool_calls"] = [{"id": call.id, "name": call.name, "arguments": call.arguments} for call in turn.tool_calls]
    for key in ("tool_call_id", "name", "raw", "provider"):
        if getattr(turn, key) is not None:
            data[key] = getattr(turn, key)
    if turn.is_error:
        data["is_error"] = True
    return data


def turn_from_dict(data: dict[str, Any]) -> ToolTurn:
    return ToolTurn(
        role=str(data.get("role") or "user"),
        content=str(data.get("content") or ""),
        tool_calls=tuple(
            ToolCall(id=str(call.get("id") or ""), name=str(call.get("name") or ""), arguments=dict(call.get("arguments") or {}))
            for call in data.get("tool_calls") or []
        ),
        tool_call_id=data.get("tool_call_id"),
        name=data.get("name"),
        is_error=bool(data.get("is_error")),
        raw=data.get("raw"),
        provider=data.get("provider"),
    )


def parse_arguments(value: Any) -> dict[str, Any]:
    """Tool arguments as a dict, whether the provider sent an object or a JSON string."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


# --- JSON fallback ---------------------------------------------------------------------------

_FALLBACK_INSTRUCTION = """You can call tools. Reply with exactly one JSON object and nothing else.

To call tools: {{"tool_calls": [{{"name": "<tool>", "arguments": {{...}}}}]}}
When you are done: {{"final": <your final answer>}}

Tools:
{tools}"""

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)


class JsonToolFallback:
    """Tool calling for a client that only has `generate`: JSON in the reply instead of tool blocks."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def generate_with_tools(self, request: ToolRequest) -> ToolResponse:
        start = time.perf_counter()
        tools = "\n".join(
            f"- {tool.name}: {tool.description} Arguments (JSON Schema): {json.dumps(tool.parameters, sort_keys=True)}"
            for tool in request.tools
        )
        messages = [LLMMessage(role="system", content=_FALLBACK_INSTRUCTION.format(tools=tools))]
        for turn in request.messages:
            messages.append(_fallback_message(turn))
        response = self.client.generate(
            LLMRequest(messages=messages, max_tokens=request.max_tokens, response_format="json", timeout_seconds=request.timeout_seconds)
        )
        content, calls = _parse_fallback_reply(response.content)
        return ToolResponse(
            content=content,
            tool_calls=calls,
            raw=None,
            model=response.model,
            provider=response.provider,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=response.latency_ms or round((time.perf_counter() - start) * 1000, 2),
        )


def _fallback_message(turn: ToolTurn) -> LLMMessage:
    if turn.role == "tool":
        status = "failed" if turn.is_error else "result"
        return LLMMessage(role="user", content=f"Tool {status} for {turn.tool_call_id} ({turn.name}):\n{turn.content}")
    if turn.role == "assistant" and turn.tool_calls:
        calls = [{"name": call.name, "arguments": call.arguments} for call in turn.tool_calls]
        return LLMMessage(role="assistant", content=json.dumps({"tool_calls": calls}, sort_keys=True))
    return LLMMessage(role=turn.role, content=turn.content)


def _parse_fallback_reply(text: str) -> tuple[str, tuple[ToolCall, ...]]:
    raw = text.strip()
    match = _FENCE.match(raw)
    if match:
        raw = match.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return text, ()
    if not isinstance(data, dict):
        return text, ()
    calls = data.get("tool_calls")
    if isinstance(calls, list) and calls:
        parsed = tuple(
            ToolCall(id=new_call_id(), name=str(call.get("name") or ""), arguments=parse_arguments(call.get("arguments")))
            for call in calls
            if isinstance(call, dict) and call.get("name")
        )
        if parsed:
            return "", parsed
    final = data.get("final", data)
    return final if isinstance(final, str) else json.dumps(final), ()


def new_call_id() -> str:
    """An id for a tool call the provider didn't name (Ollama, the JSON fallback)."""
    return f"call_{uuid.uuid4().hex[:12]}"
