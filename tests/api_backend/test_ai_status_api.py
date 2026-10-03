"""AI provider status and connection test (Integrations page card).

The status shows the provider the backend started with, whether AI is actually in use, and why
not; it never returns secrets. The test sends one short request through the running client.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.ai.config import AIConfig
from backend.app.ai.exceptions import LLMRequestError
from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.interfaces import LLMRequest, LLMResponse
from backend.app.ai.models import StructuredLLMService
from backend.app.api import ai as ai_module
from backend.app.api import assistant as assistant_module


class _FakeClient:
    def __init__(self, *, reply: str = "ok", fail: str | None = None) -> None:
        self.reply = reply
        self.fail = fail
        self.model = "qwen2.5-7b"
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self.fail:
            raise LLMRequestError(self.fail)
        return LLMResponse(content=self.reply, model=self.model, provider="openai_compatible", latency_ms=12.5)


def _use(monkeypatch: pytest.MonkeyPatch, config: AIConfig | None, client: _FakeClient | None = None) -> None:
    monkeypatch.setitem(ai_module._services, "config", config)
    assistant = None
    if client is not None:
        services = OptionalAIServices(client=client, structured=StructuredLLMService(client))
        assistant = SimpleNamespace(services=SimpleNamespace(ai_services=services))
    monkeypatch.setitem(assistant_module._services, "assistant", assistant)


_CONFIGURED = AIConfig(
    enabled=True,
    provider="openai_compatible",
    openai_compatible={
        "base_url": "https://user:hunter2@llm.internal:8443/v1?api-key=query-secret",
        "model": "qwen2.5-7b",
        "api_key": "sk-very-secret",
    },
)


def test_status_is_off_by_default(client, monkeypatch) -> None:
    _use(monkeypatch, AIConfig())

    body = client.get("/api/ai/status").json()

    assert body["enabled"] is False
    assert body["active"] is False
    assert body["issue"] is None


def test_status_explains_a_misconfigured_provider(client, monkeypatch) -> None:
    _use(monkeypatch, AIConfig(enabled=True, provider="openai_compatible", openai_compatible={"base_url": "http://vllm:8000/v1"}))

    body = client.get("/api/ai/status").json()

    assert body["active"] is False
    assert "model" in body["issue"]


def test_status_explains_an_unknown_provider(client, monkeypatch) -> None:
    _use(monkeypatch, AIConfig(enabled=True, provider="gpt"))

    body = client.get("/api/ai/status").json()

    assert body["active"] is False
    assert "gpt" in body["issue"]


def test_status_explains_ai_unused_when_the_assistant_is_not_running(client, monkeypatch) -> None:
    _use(monkeypatch, _CONFIGURED, client=None)

    body = client.get("/api/ai/status").json()

    assert body["enabled"] is True
    assert body["active"] is False
    assert "memory" in body["issue"].lower()


def test_status_shows_the_active_provider_without_secrets(client, monkeypatch) -> None:
    _use(monkeypatch, _CONFIGURED, client=_FakeClient())

    response = client.get("/api/ai/status")
    body = response.json()

    assert body["active"] is True
    assert body["issue"] is None
    assert body["provider"] == "openai_compatible"
    assert body["model"] == "qwen2.5-7b"
    assert body["endpoint"] == "https://llm.internal:8443/v1"
    assert body["api_key_set"] is True
    for secret in ("sk-very-secret", "hunter2", "query-secret"):
        assert secret not in response.text


def test_status_for_anthropic_uses_the_default_endpoint(client, monkeypatch) -> None:
    _use(monkeypatch, AIConfig(enabled=True, provider="anthropic"), client=_FakeClient())

    body = client.get("/api/ai/status").json()

    assert body["model"] == "claude-opus-5"
    assert body["endpoint"] == "https://api.anthropic.com"


def test_connection_test_sends_one_request_through_the_running_client(client, monkeypatch) -> None:
    fake = _FakeClient(reply="ok")
    _use(monkeypatch, _CONFIGURED, client=fake)

    body = client.post("/api/ai/test").json()

    assert body["ok"] is True
    assert body["reply"] == "ok"
    assert body["model"] == "qwen2.5-7b"
    assert body["latency_ms"] == 12.5
    assert body["error"] is None
    assert len(fake.requests) == 1


def test_connection_test_reports_the_provider_error(client, monkeypatch) -> None:
    _use(monkeypatch, _CONFIGURED, client=_FakeClient(fail="OpenAI-compatible endpoint returned HTTP 401: Incorrect API key provided"))

    body = client.post("/api/ai/test").json()

    assert body["ok"] is False
    assert "401" in body["error"]


def test_connection_test_when_ai_is_off(client, monkeypatch) -> None:
    _use(monkeypatch, AIConfig())

    body = client.post("/api/ai/test").json()

    assert body["ok"] is False
    assert "off" in body["error"].lower()


def test_connection_test_when_misconfigured_reports_the_issue(client, monkeypatch) -> None:
    _use(monkeypatch, AIConfig(enabled=True, provider="openai_compatible", openai_compatible={"base_url": "http://vllm:8000/v1"}))

    body = client.post("/api/ai/test").json()

    assert body["ok"] is False
    assert "model" in body["error"]
