"""OpenAI-compatible chat completions adapter (vLLM, Azure OpenAI, Bedrock gateways, LiteLLM)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Sequence

from backend.app.ai.exceptions import LLMRequestError
from backend.app.ai.interfaces import LLMClient, LLMRequest, LLMResponse
from backend.app.ai.tool_calls import ToolCall, ToolRequest, ToolResponse, ToolTurn, new_call_id, parse_arguments


# Thinking models served behind OpenAI-compatible endpoints (e.g. Gemini 3.x, reasoning gateways,
# DeepSeek/Qwen on vLLM) count internal thinking tokens against `max_tokens`. Features size
# `max_tokens` for the answer alone (8-400 tokens), so once a server reports hidden reasoning
# tokens, add room for thinking on this client; only tokens actually written are billed.
THINKING_HEADROOM_TOKENS = 4000


class OpenAICompatibleLLMClient(LLMClient):
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        api_key_header: str = "Authorization",
        headers: dict[str, str] | None = None,
        json_mode: bool = True,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.api_key_header = api_key_header
        self.headers = dict(headers or {})
        self.json_mode = json_mode
        self.timeout_seconds = timeout_seconds
        self._needs_thinking_headroom = False

    def _effective_max_tokens(self, max_tokens: int | None) -> int | None:
        if max_tokens is None:
            return None
        return max_tokens + THINKING_HEADROOM_TOKENS if self._needs_thinking_headroom else max_tokens

    def _post_with_thinking_retry(self, payload: dict[str, object], requested_max_tokens: int | None, timeout_seconds: float | None) -> dict:
        data = self._post(payload, timeout_seconds)
        if _used_reasoning_tokens(data):
            was_known = self._needs_thinking_headroom
            self._needs_thinking_headroom = True
            if not was_known and requested_max_tokens is not None and _finish_reason(data) == "length":
                retry_payload = {**payload, "max_tokens": requested_max_tokens + THINKING_HEADROOM_TOKENS}
                data = self._post(retry_payload, timeout_seconds)
        return data

    def generate(self, request: LLMRequest) -> LLMResponse:
        start = time.perf_counter()
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [{"role": message.role, "content": message.content} for message in request.messages],
            "temperature": request.temperature,
        }
        effective_max_tokens = self._effective_max_tokens(request.max_tokens)
        if effective_max_tokens is not None:
            payload["max_tokens"] = effective_max_tokens
        if request.response_format == "json" and self.json_mode:
            payload["response_format"] = {"type": "json_object"}

        data = self._post_with_thinking_retry(payload, request.max_tokens, request.timeout_seconds)

        content = ""
        choices = data.get("choices") if isinstance(data, dict) else None
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                content = str(message.get("content") or "").strip()
        if not content:
            if _finish_reason(data) == "length":
                raise LLMRequestError("OpenAI-compatible endpoint ran out of tokens before writing an answer (max_tokens reached while thinking)")
            raise LLMRequestError("OpenAI-compatible endpoint returned an empty response")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return LLMResponse(
            content=content,
            model=str(data.get("model") or self.model),
            provider="openai_compatible",
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
        )

    def generate_with_tools(self, request: ToolRequest) -> ToolResponse:
        """One turn of a tool conversation through the chat completions `tools` API.

        The provider's assistant message is kept in `raw` and sent back unchanged on the next turn
        so opaque provider fields (such as reasoning/thought signatures on tool calls) survive
        multi-turn tool loops.
        """
        start = time.perf_counter()
        payload: dict[str, object] = {
            "model": self.model,
            "messages": _tool_messages(request.messages),
            "tools": [
                {"type": "function", "function": {"name": tool.name, "description": tool.description, "parameters": tool.parameters}}
                for tool in request.tools
            ],
        }
        effective_max_tokens = self._effective_max_tokens(request.max_tokens)
        if effective_max_tokens is not None:
            payload["max_tokens"] = effective_max_tokens
        data = self._post_with_thinking_retry(payload, request.max_tokens, request.timeout_seconds)

        message: dict = {}
        choices = data.get("choices") if isinstance(data, dict) else None
        if isinstance(choices, list) and choices and isinstance(choices[0], dict) and isinstance(choices[0].get("message"), dict):
            message = choices[0]["message"]
        content = str(message.get("content") or "").strip()
        calls: list[ToolCall] = []
        raw_calls: list[dict[str, object]] = []
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict) or not (call.get("function") or {}).get("name"):
                continue
            call_id = str(call.get("id") or new_call_id())
            fn = call["function"]
            calls.append(ToolCall(id=call_id, name=str(fn["name"]), arguments=parse_arguments(fn.get("arguments"))))
            raw_call = dict(call)
            raw_call["id"] = call_id
            raw_calls.append(raw_call)
        if not content and not calls:
            if _finish_reason(data) == "length":
                raise LLMRequestError("OpenAI-compatible endpoint ran out of tokens before writing an answer (max_tokens reached while thinking)")
            raise LLMRequestError("OpenAI-compatible endpoint returned an empty response")
        raw_message: dict[str, object] | None = None
        if message:
            raw_message = dict(message)
            raw_message.setdefault("role", "assistant")
            if raw_calls:
                raw_message["tool_calls"] = raw_calls
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return ToolResponse(
            content=content,
            tool_calls=tuple(calls),
            raw=raw_message,
            model=str(data.get("model") or self.model),
            provider="openai_compatible",
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
        )

    def _post(self, payload: dict[str, object], timeout_seconds: float | None) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds or self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise LLMRequestError(f"OpenAI-compatible endpoint returned HTTP {exc.code}: {_error_detail(exc)}") from exc
        except urllib.error.URLError as exc:
            raise LLMRequestError(f"Failed to reach OpenAI-compatible endpoint at {self.base_url}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise LLMRequestError(f"OpenAI-compatible endpoint returned invalid JSON: {exc}") from exc
        except TimeoutError as exc:
            raise LLMRequestError(f"OpenAI-compatible request timed out: {exc}") from exc
        return data if isinstance(data, dict) else {}

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json", **self.headers}
        if self.api_key:
            if self.api_key_header.lower() == "authorization":
                headers["Authorization"] = f"Bearer {self.api_key}"
            else:
                headers[self.api_key_header] = self.api_key
        return headers


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        return str(exc.reason)
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body[:500] or str(exc.reason)
    error = parsed.get("error") if isinstance(parsed, dict) else None
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    if isinstance(error, str):
        return error
    return body[:500]


def _finish_reason(data: dict) -> str | None:
    choices = data.get("choices") if isinstance(data, dict) else None
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        reason = choices[0].get("finish_reason")
        return str(reason) if reason is not None else None
    return None


def _used_reasoning_tokens(data: dict) -> bool:
    """True when the response spent hidden reasoning/thinking tokens against max_tokens."""
    usage = data.get("usage") if isinstance(data, dict) else None
    if isinstance(usage, dict):
        details = usage.get("completion_tokens_details")
        if isinstance(details, dict) and (details.get("reasoning_tokens") or 0) > 0:
            return True
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        total = usage.get("total_tokens")
        if isinstance(prompt, int) and isinstance(completion, int) and isinstance(total, int):
            if total > prompt + completion:
                return True
    choices = data.get("choices") if isinstance(data, dict) else None
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict) and (message.get("reasoning_content") or message.get("reasoning")):
            return True
    return False


def _tool_messages(turns: Sequence[ToolTurn]) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    for turn in turns:
        if turn.role == "tool":
            messages.append({"role": "tool", "tool_call_id": turn.tool_call_id, "content": turn.content})
        elif turn.role == "assistant" and turn.raw is not None and turn.provider == "openai_compatible" and isinstance(turn.raw, dict):
            messages.append(turn.raw)
        elif turn.role == "assistant" and turn.tool_calls:
            messages.append({
                "role": "assistant",
                "content": turn.content or None,
                "tool_calls": [
                    {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": json.dumps(call.arguments)}}
                    for call in turn.tool_calls
                ],
            })
        else:
            messages.append({"role": turn.role, "content": turn.content})
    return messages
