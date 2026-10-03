"""OpenAI-compatible chat completions adapter (vLLM, Azure OpenAI, Bedrock gateways, LiteLLM)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from backend.app.ai.exceptions import LLMRequestError
from backend.app.ai.interfaces import LLMClient, LLMRequest, LLMResponse


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

    def generate(self, request: LLMRequest) -> LLMResponse:
        start = time.perf_counter()
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [{"role": message.role, "content": message.content} for message in request.messages],
            "temperature": request.temperature,
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.response_format == "json" and self.json_mode:
            payload["response_format"] = {"type": "json_object"}

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=request.timeout_seconds or self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise LLMRequestError(f"OpenAI-compatible endpoint returned HTTP {exc.code}: {_error_detail(exc)}") from exc
        except urllib.error.URLError as exc:
            raise LLMRequestError(f"Failed to reach OpenAI-compatible endpoint at {self.base_url}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise LLMRequestError(f"OpenAI-compatible endpoint returned invalid JSON: {exc}") from exc
        except TimeoutError as exc:
            raise LLMRequestError(f"OpenAI-compatible request timed out: {exc}") from exc

        content = ""
        choices = data.get("choices") if isinstance(data, dict) else None
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                content = str(message.get("content") or "").strip()
        if not content:
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
