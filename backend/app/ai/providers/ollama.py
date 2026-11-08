"""Ollama provider adapter."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Sequence

from backend.app.ai.exceptions import LLMRequestError
from backend.app.ai.interfaces import LLMClient, LLMMessage, LLMRequest, LLMResponse
from backend.app.ai.tool_calls import ToolCall, ToolRequest, ToolResponse, ToolTurn, new_call_id, parse_arguments


class OllamaLLMClient(LLMClient):
    def __init__(self, base_url: str, model: str, timeout_seconds: float = 30.0, min_timeout_seconds: float | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.min_timeout_seconds = min_timeout_seconds

    def timeout_for(self, request: LLMRequest) -> float:
        """The feature's own limit, raised to min_timeout_seconds when that's set (a model on CPU)."""
        timeout = request.timeout_seconds or self.timeout_seconds
        return max(timeout, self.min_timeout_seconds) if self.min_timeout_seconds else timeout

    def generate(self, request: LLMRequest) -> LLMResponse:
        start = time.perf_counter()
        payload = {
            "model": self.model,
            "messages": [{"role": message.role, "content": message.content} for message in request.messages],
            "stream": False,
            "options": {
                "temperature": request.temperature,
            },
        }
        if request.max_tokens is not None:
            payload["options"]["num_predict"] = request.max_tokens
        if request.response_format == "json":
            payload["format"] = "json"

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_for(request)) as response:
                raw = response.read().decode("utf-8")
            data = json.loads(raw)
            content = ""
            if isinstance(data.get("message"), dict):
                content = str(data["message"].get("content", "")).strip()
            if not content:
                raise LLMRequestError("Ollama returned an empty response")
            return LLMResponse(
                content=content,
                model=self.model,
                provider="ollama",
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
            )
        except urllib.error.URLError as exc:
            raise LLMRequestError(f"Failed to reach Ollama at {self.base_url}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise LLMRequestError(f"Ollama returned invalid JSON: {exc}") from exc
        except TimeoutError as exc:
            raise LLMRequestError(f"Ollama request timed out: {exc}") from exc

    def generate_with_tools(self, request: ToolRequest) -> ToolResponse:
        """One turn of a tool conversation through /api/chat `tools`. Only models trained for tool
        calling use them (qwen2.5, llama3.1 and later); others answer in plain text, which ends the
        investigation with that text as the answer."""
        start = time.perf_counter()
        payload: dict[str, object] = {
            "model": self.model,
            "messages": _tool_messages(request.messages),
            "tools": [
                {"type": "function", "function": {"name": tool.name, "description": tool.description, "parameters": tool.parameters}}
                for tool in request.tools
            ],
            "stream": False,
        }
        if request.max_tokens is not None:
            payload["options"] = {"num_predict": request.max_tokens}
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_for(LLMRequest(messages=[], timeout_seconds=request.timeout_seconds))) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise LLMRequestError(f"Failed to reach Ollama at {self.base_url}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise LLMRequestError(f"Ollama returned invalid JSON: {exc}") from exc
        except TimeoutError as exc:
            raise LLMRequestError(f"Ollama request timed out: {exc}") from exc
        message = data.get("message") if isinstance(data, dict) and isinstance(data.get("message"), dict) else {}
        content = str(message.get("content") or "").strip()
        calls = tuple(
            ToolCall(
                id=str(call.get("id") or new_call_id()),
                name=str((call.get("function") or {}).get("name") or ""),
                arguments=parse_arguments((call.get("function") or {}).get("arguments")),
            )
            for call in message.get("tool_calls") or []
            if isinstance(call, dict) and (call.get("function") or {}).get("name")
        )
        if not content and not calls:
            raise LLMRequestError("Ollama returned an empty response")
        return ToolResponse(
            content=content,
            tool_calls=calls,
            model=self.model,
            provider="ollama",
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
        )


def _tool_messages(turns: Sequence[ToolTurn]) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    for turn in turns:
        if turn.role == "tool":
            messages.append({"role": "tool", "content": turn.content, "tool_name": turn.name})
        elif turn.role == "assistant" and turn.tool_calls:
            messages.append({
                "role": "assistant",
                "content": turn.content,
                "tool_calls": [{"function": {"name": call.name, "arguments": call.arguments}} for call in turn.tool_calls],
            })
        else:
            messages.append({"role": turn.role, "content": turn.content})
    return messages
