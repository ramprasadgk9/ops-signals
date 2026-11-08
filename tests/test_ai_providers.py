"""AI provider choice: no LLM by default, plus OpenAI-compatible and Anthropic providers.

The OpenAI-compatible client is exercised through a faked urlopen and the Anthropic client through
a faked SDK client, so the real request building and response parsing run without a network.
"""

from __future__ import annotations

import dataclasses
import io
import json
import urllib.error
from types import SimpleNamespace

import pytest

from backend.app.ai.config import AIConfig, apply_ai_env_overrides
from backend.app.ai.exceptions import LLMRequestError
from backend.app.ai.factory import build_llm_client, build_optional_ai_services
from backend.app.ai.interfaces import LLMMessage, LLMRequest
from backend.app.ai.providers import anthropic as anthropic_provider
from backend.app.ai.providers import openai_compatible
from backend.app.ai.providers import ollama as ollama_provider
from backend.app.ai.providers.anthropic import THINKING_HEADROOM_TOKENS, AnthropicLLMClient
from backend.app.ai.providers.noop import NoOpLLMClient
from backend.app.ai.providers.ollama import OllamaLLMClient
from backend.app.ai.providers.openai_compatible import OpenAICompatibleLLMClient


def _request(response_format: str | None = None) -> LLMRequest:
    return LLMRequest(
        messages=[
            LLMMessage(role="system", content="You explain operational findings."),
            LLMMessage(role="user", content="Why did checkout latency rise?"),
        ],
        temperature=0.0,
        max_tokens=300,
        response_format=response_format,
    )


class _FakeHTTPResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(captured: dict, body: dict):
    def urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = {key.lower(): value for key, value in req.header_items()}
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeHTTPResponse(json.dumps(body).encode("utf-8"))

    return urlopen


_CHAT_COMPLETION = {
    "model": "served-model",
    "choices": [{"message": {"role": "assistant", "content": "  A deploy at 14:02 doubled p99.  "}}],
    "usage": {"prompt_tokens": 42, "completion_tokens": 9},
}


# --- default stays "no LLM required" -------------------------------------------------------


def test_ai_is_off_by_default() -> None:
    config = AIConfig()

    assert config.enabled is False
    assert isinstance(build_llm_client(config), NoOpLLMClient)
    assert build_optional_ai_services(config) is None


def test_unknown_provider_falls_back_to_no_llm() -> None:
    assert isinstance(build_llm_client(AIConfig(enabled=True, provider="not-a-provider")), NoOpLLMClient)


# --- factory -------------------------------------------------------------------------------


def test_factory_builds_each_provider() -> None:
    assert isinstance(build_llm_client(AIConfig(enabled=True, provider="ollama")), OllamaLLMClient)

    openai_config = AIConfig(
        enabled=True,
        provider="openai_compatible",
        openai_compatible={"base_url": "http://vllm:8000/v1", "model": "qwen2.5-7b"},
    )
    assert isinstance(build_llm_client(openai_config), OpenAICompatibleLLMClient)

    anthropic_config = AIConfig(enabled=True, provider="anthropic", anthropic={"api_key": "test-key"})
    client = build_llm_client(anthropic_config)
    assert isinstance(client, AnthropicLLMClient)
    assert client.model == "claude-opus-5"


def test_openai_compatible_without_model_falls_back_to_no_llm() -> None:
    config = AIConfig(enabled=True, provider="openai_compatible", openai_compatible={"base_url": "http://vllm:8000/v1"})

    assert isinstance(build_llm_client(config), NoOpLLMClient)


# --- OpenAI-compatible ---------------------------------------------------------------------


def test_openai_compatible_sends_chat_completion_with_bearer_key(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(openai_compatible.urllib.request, "urlopen", _fake_urlopen(captured, _CHAT_COMPLETION))
    client = OpenAICompatibleLLMClient(base_url="http://vllm:8000/v1/", model="qwen2.5-7b", api_key="secret")

    response = client.generate(_request())

    assert captured["url"] == "http://vllm:8000/v1/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer secret"
    assert captured["body"]["model"] == "qwen2.5-7b"
    assert captured["body"]["messages"][0] == {"role": "system", "content": "You explain operational findings."}
    assert captured["body"]["temperature"] == 0.0
    assert captured["body"]["max_tokens"] == 300
    assert "response_format" not in captured["body"]
    assert response.content == "A deploy at 14:02 doubled p99."
    assert response.provider == "openai_compatible"
    assert (response.input_tokens, response.output_tokens) == (42, 9)


def test_openai_compatible_supports_azure_api_key_header_and_json_mode(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(openai_compatible.urllib.request, "urlopen", _fake_urlopen(captured, _CHAT_COMPLETION))
    client = OpenAICompatibleLLMClient(
        base_url="https://my-resource.openai.azure.com/openai/v1",
        model="my-deployment",
        api_key="azure-key",
        api_key_header="api-key",
    )

    client.generate(_request(response_format="json"))

    assert captured["headers"]["api-key"] == "azure-key"
    assert "authorization" not in captured["headers"]
    assert captured["body"]["response_format"] == {"type": "json_object"}


def test_openai_compatible_json_mode_can_be_turned_off(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(openai_compatible.urllib.request, "urlopen", _fake_urlopen(captured, _CHAT_COMPLETION))
    client = OpenAICompatibleLLMClient(base_url="http://gw/v1", model="m", json_mode=False)

    client.generate(_request(response_format="json"))

    assert "response_format" not in captured["body"]


def test_openai_compatible_http_error_keeps_the_server_message(monkeypatch) -> None:
    def urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"error": {"message": "Incorrect API key provided"}}')
        )

    monkeypatch.setattr(openai_compatible.urllib.request, "urlopen", urlopen)
    client = OpenAICompatibleLLMClient(base_url="http://gw/v1", model="m", api_key="bad")

    with pytest.raises(LLMRequestError, match="401.*Incorrect API key provided"):
        client.generate(_request())


def test_openai_compatible_empty_content_is_an_error(monkeypatch) -> None:
    monkeypatch.setattr(
        openai_compatible.urllib.request,
        "urlopen",
        _fake_urlopen({}, {"choices": [{"message": {"content": ""}}]}),
    )
    client = OpenAICompatibleLLMClient(base_url="http://gw/v1", model="m")

    with pytest.raises(LLMRequestError, match="empty response"):
        client.generate(_request())


# --- Anthropic -----------------------------------------------------------------------------


class _FakeAnthropicMessages:
    def __init__(self, response) -> None:
        self.response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def _anthropic_response(text: str = "Checkout p99 rose after the 14:02 deploy.", stop_reason: str = "end_turn"):
    return SimpleNamespace(
        model="claude-opus-5",
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=120, output_tokens=15),
    )


def test_anthropic_moves_system_messages_and_omits_temperature() -> None:
    messages = _FakeAnthropicMessages(_anthropic_response())
    client = AnthropicLLMClient(model="claude-opus-5", client=SimpleNamespace(messages=messages))

    response = client.generate(_request())

    call = messages.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["system"] == "You explain operational findings."
    assert call["messages"] == [{"role": "user", "content": "Why did checkout latency rise?"}]
    # The caller's 300 is for the answer; thinking gets its own room on top.
    assert call["max_tokens"] == 300 + THINKING_HEADROOM_TOKENS
    assert "temperature" not in call
    assert "output_config" not in call
    assert response.content == "Checkout p99 rose after the 14:02 deploy."
    assert response.provider == "anthropic"
    assert (response.input_tokens, response.output_tokens) == (120, 15)


def test_anthropic_uses_default_max_tokens_and_configured_effort() -> None:
    messages = _FakeAnthropicMessages(_anthropic_response())
    client = AnthropicLLMClient(model="claude-opus-5", effort="low", client=SimpleNamespace(messages=messages))

    client.generate(LLMRequest(messages=[LLMMessage(role="user", content="hi")]))

    call = messages.calls[0]
    assert call["max_tokens"] == 16000
    assert call["output_config"] == {"effort": "low"}
    assert "system" not in call


def test_anthropic_refusal_is_an_error() -> None:
    messages = _FakeAnthropicMessages(_anthropic_response(text="", stop_reason="refusal"))
    client = AnthropicLLMClient(model="claude-opus-5", client=SimpleNamespace(messages=messages))

    with pytest.raises(LLMRequestError, match="refused"):
        client.generate(_request())


def test_anthropic_running_out_of_tokens_while_thinking_says_so() -> None:
    messages = _FakeAnthropicMessages(_anthropic_response(text="", stop_reason="max_tokens"))
    client = AnthropicLLMClient(model="claude-haiku-5-5", client=SimpleNamespace(messages=messages))

    with pytest.raises(LLMRequestError, match="ran out of tokens"):
        client.generate(_request())


def test_anthropic_sdk_errors_become_llm_request_errors() -> None:
    class _FailingMessages:
        def create(self, **kwargs):
            raise anthropic_provider.anthropic.APIError("overloaded", request=None, body=None)

    client = AnthropicLLMClient(model="claude-opus-5", client=SimpleNamespace(messages=_FailingMessages()))

    with pytest.raises(LLMRequestError, match="overloaded"):
        client.generate(_request())


# --- environment overrides -----------------------------------------------------------------


def test_env_overrides_configure_each_provider(monkeypatch) -> None:
    monkeypatch.setenv("OPS_SIGNALS_AI_ENABLED", "true")
    monkeypatch.setenv("OPS_SIGNALS_AI_PROVIDER", "openai_compatible")
    monkeypatch.setenv("OPS_SIGNALS_OLLAMA_MODEL", "llama3.2:latest")
    monkeypatch.setenv("OPS_SIGNALS_OPENAI_BASE_URL", "http://vllm:8000/v1")
    monkeypatch.setenv("OPS_SIGNALS_OPENAI_MODEL", "qwen2.5-7b")
    monkeypatch.setenv("OPS_SIGNALS_OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("OPS_SIGNALS_OPENAI_API_KEY_HEADER", "api-key")
    monkeypatch.setenv("OPS_SIGNALS_ANTHROPIC_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("OPS_SIGNALS_ANTHROPIC_API_KEY", "anthropic-secret")

    config = apply_ai_env_overrides(AIConfig())

    assert config.enabled is True
    assert config.provider == "openai_compatible"
    assert config.ollama.model == "llama3.2:latest"
    assert config.openai_compatible.base_url == "http://vllm:8000/v1"
    assert config.openai_compatible.model == "qwen2.5-7b"
    assert config.openai_compatible.api_key == "openai-secret"
    assert config.openai_compatible.api_key_header == "api-key"
    assert config.anthropic.model == "claude-sonnet-5"
    assert config.anthropic.api_key == "anthropic-secret"


def test_ollama_sends_the_callers_token_limit_and_timeout_unchanged(monkeypatch) -> None:
    """Short calls (alert-enrichment summaries, intent classification) rely on their own small
    limits to fail fast; callers that need room, like comment triage, ask for it themselves."""
    captured: dict = {}
    body = {"message": {"role": "assistant", "content": "deploy regression"}, "prompt_eval_count": 12, "eval_count": 3}
    monkeypatch.setattr(ollama_provider.urllib.request, "urlopen", _fake_urlopen(captured, body))
    client = OllamaLLMClient(base_url="http://ollama:11434", model="qwen2.5", timeout_seconds=30.0)

    response = client.generate(dataclasses.replace(_request(), max_tokens=120, timeout_seconds=10))

    assert captured["url"] == "http://ollama:11434/api/chat"
    assert captured["body"]["options"]["num_predict"] == 120
    assert captured["timeout"] == 10
    assert response.content == "deploy regression"


def test_ollama_short_answers_ask_a_thinking_model_not_to_think(monkeypatch) -> None:
    """A thinking model (qwen3) given a 200-token draft spent it all thinking and returned no text."""
    captured: dict = {}
    body = {"message": {"role": "assistant", "content": "Traffic dropped at 22:02."}}
    monkeypatch.setattr(ollama_provider.urllib.request, "urlopen", _fake_urlopen(captured, body))

    OllamaLLMClient(base_url="http://ollama:11434", model="qwen3:14b").generate(dataclasses.replace(_request(), max_tokens=200))

    assert captured["body"]["think"] is False


def test_ollama_waits_at_least_its_minimum_for_a_model_on_cpu(monkeypatch) -> None:
    # A feature asking 15 s timed out on every answer from a CPU-only model (10-20 s each).
    captured: dict = {}
    body = {"message": {"role": "assistant", "content": "deploy regression"}}
    monkeypatch.setattr(ollama_provider.urllib.request, "urlopen", _fake_urlopen(captured, body))
    client = OllamaLLMClient(base_url="http://ollama:11434", model="gemma3:4b", timeout_seconds=30.0, min_timeout_seconds=90.0)

    client.generate(dataclasses.replace(_request(), timeout_seconds=15))
    assert captured["timeout"] == 90.0
    client.generate(dataclasses.replace(_request(), timeout_seconds=120))
    assert captured["timeout"] == 120


def test_the_ollama_minimum_comes_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("OPS_SIGNALS_AI_ENABLED", "true")
    monkeypatch.setenv("OPS_SIGNALS_AI_PROVIDER", "ollama")
    monkeypatch.setenv("OPS_SIGNALS_OLLAMA_TIMEOUT_SECONDS", "90")
    config = apply_ai_env_overrides(AIConfig())

    assert config.ollama.min_timeout_seconds == 90.0
    assert build_llm_client(config).min_timeout_seconds == 90.0
    assert apply_ai_env_overrides(AIConfig()).ollama.min_timeout_seconds == 90.0
    monkeypatch.delenv("OPS_SIGNALS_OLLAMA_TIMEOUT_SECONDS")
    assert apply_ai_env_overrides(AIConfig()).ollama.min_timeout_seconds is None
