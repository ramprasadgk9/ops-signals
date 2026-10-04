"""Ollama provider adapter."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from backend.app.ai.exceptions import LLMRequestError
from backend.app.ai.interfaces import LLMClient, LLMMessage, LLMRequest, LLMResponse


class OllamaLLMClient(LLMClient):
    def __init__(self, base_url: str, model: str, timeout_seconds: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

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
            payload["options"]["num_predict"] = max(request.max_tokens, 1000)
        if request.response_format == "json":
            payload["format"] = "json"

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        effective_timeout = max(request.timeout_seconds or 0, self.timeout_seconds, 60.0)
        try:
            with urllib.request.urlopen(req, timeout=effective_timeout) as response:
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
