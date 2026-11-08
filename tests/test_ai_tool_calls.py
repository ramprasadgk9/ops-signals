"""Tool calling: each provider turns one tool conversation into one reply, and a client without
native tool calling gets the JSON fallback. Providers run against faked transports, as in
test_ai_providers.py, so the real request building and reply parsing run without a network."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

from backend.app.ai.exceptions import LLMRequestError
from backend.app.ai.interfaces import LLMRequest, LLMResponse
from backend.app.ai.providers import ollama as ollama_provider
from backend.app.ai.providers import openai_compatible
from backend.app.ai.providers.anthropic import AnthropicLLMClient
from backend.app.ai.providers.ollama import OllamaLLMClient
from backend.app.ai.providers.openai_compatible import OpenAICompatibleLLMClient
from backend.app.ai.tool_calls import (
    JsonToolFallback,
    ToolCall,
    ToolRequest,
    ToolSpec,
    ToolTurn,
    generate_with_tools,
    turn_from_dict,
    turn_to_dict,
)

TOOLS = [ToolSpec(name="query_range", description="Run a PromQL range query.", parameters={"type": "object", "properties": {"promql": {"type": "string"}}, "required": ["promql"]})]


def _conversation() -> list[ToolTurn]:
    call = ToolCall(id="toolu_1", name="query_range", arguments={"promql": "rate(errors[5m])"})
    return [
        ToolTurn(role="system", content="You help an on-call engineer."),
        ToolTurn(role="user", content="Checkout errors rose at 10:00."),
        ToolTurn(role="assistant", content="", tool_calls=(call,)),
        ToolTurn(role="tool", content="flat at 0.2/s", tool_call_id="toolu_1", name="query_range"),
    ]


# --- Anthropic -----------------------------------------------------------------------------


class _FakeMessages:
    def __init__(self, response) -> None:
        self.response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def _block(**fields):
    block = SimpleNamespace(**fields)
    block.to_dict = lambda: dict(fields)
    return block


def test_anthropic_returns_tool_calls_and_keeps_the_blocks_to_send_back() -> None:
    response = SimpleNamespace(
        model="claude-opus-5",
        stop_reason="tool_use",
        content=[
            _block(type="thinking", thinking="", signature="sig"),
            _block(type="tool_use", id="toolu_2", name="query_range", input={"promql": "sum(rate(requests[5m]))"}),
        ],
        usage=SimpleNamespace(input_tokens=200, output_tokens=30),
    )
    messages = _FakeMessages(response)
    client = AnthropicLLMClient(client=SimpleNamespace(messages=messages))

    reply = client.generate_with_tools(ToolRequest(messages=_conversation(), tools=TOOLS, max_tokens=800))

    assert reply.tool_calls == (ToolCall(id="toolu_2", name="query_range", arguments={"promql": "sum(rate(requests[5m]))"}),)
    assert reply.raw[0] == {"type": "thinking", "thinking": "", "signature": "sig"}
    sent = messages.calls[0]
    assert sent["system"] == "You help an on-call engineer."
    assert sent["tools"][0]["input_schema"]["required"] == ["promql"]
    assert sent["messages"][1]["content"][0] == {"type": "tool_use", "id": "toolu_1", "name": "query_range", "input": {"promql": "rate(errors[5m])"}}
    assert sent["messages"][2] == {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "flat at 0.2/s"}]}


def test_anthropic_sends_its_own_blocks_back_unchanged_and_all_results_in_one_message() -> None:
    raw = [{"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "tool_use", "id": "a", "name": "query_range", "input": {}}, {"type": "tool_use", "id": "b", "name": "query_range", "input": {}}]
    turns = [
        ToolTurn(role="user", content="start"),
        ToolTurn(role="assistant", tool_calls=(ToolCall("a", "query_range", {}), ToolCall("b", "query_range", {})), raw=raw, provider="anthropic"),
        ToolTurn(role="tool", content="one", tool_call_id="a", name="query_range"),
        ToolTurn(role="tool", content="Prometheus timed out", tool_call_id="b", name="query_range", is_error=True),
    ]
    response = SimpleNamespace(model="m", stop_reason="end_turn", content=[_block(type="text", text="Done.")], usage=None)
    messages = _FakeMessages(response)

    reply = AnthropicLLMClient(client=SimpleNamespace(messages=messages)).generate_with_tools(ToolRequest(messages=turns, tools=TOOLS))

    assert reply.content == "Done." and reply.tool_calls == ()
    sent = messages.calls[0]["messages"]
    assert sent[1] == {"role": "assistant", "content": raw}
    assert [block["tool_use_id"] for block in sent[2]["content"]] == ["a", "b"]
    assert sent[2]["content"][1]["is_error"] is True


def test_anthropic_refusal_in_a_tool_turn_is_an_error() -> None:
    response = SimpleNamespace(model="m", stop_reason="refusal", content=[], usage=None)
    client = AnthropicLLMClient(client=SimpleNamespace(messages=_FakeMessages(response)))

    with pytest.raises(LLMRequestError, match="refused"):
        client.generate_with_tools(ToolRequest(messages=_conversation(), tools=TOOLS))


# --- OpenAI-compatible and Ollama ----------------------------------------------------------


class _FakeHTTPResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(captured: dict, body: dict):
    def urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["url"] = req.full_url
        return _FakeHTTPResponse(json.dumps(body).encode("utf-8"))

    return urlopen


def test_openai_compatible_sends_tools_and_parses_string_arguments(monkeypatch) -> None:
    captured: dict = {}
    body = {
        "model": "served",
        "choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_9", "type": "function", "function": {"name": "query_range", "arguments": "{\"promql\": \"up\"}"}}
        ]}}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 5},
    }
    monkeypatch.setattr(openai_compatible.urllib.request, "urlopen", _fake_urlopen(captured, body))
    client = OpenAICompatibleLLMClient(base_url="http://llm/v1", model="m")

    reply = client.generate_with_tools(ToolRequest(messages=_conversation(), tools=TOOLS))

    assert reply.tool_calls == (ToolCall(id="call_9", name="query_range", arguments={"promql": "up"}),)
    sent = captured["body"]
    assert "response_format" not in sent
    assert sent["tools"][0]["function"]["name"] == "query_range"
    assert sent["messages"][2]["tool_calls"][0]["function"]["arguments"] == json.dumps({"promql": "rate(errors[5m])"})
    assert sent["messages"][3] == {"role": "tool", "tool_call_id": "toolu_1", "content": "flat at 0.2/s"}


def test_ollama_names_calls_it_returns_without_ids(monkeypatch) -> None:
    captured: dict = {}
    body = {"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "query_range", "arguments": {"promql": "up"}}}]}}
    monkeypatch.setattr(ollama_provider.urllib.request, "urlopen", _fake_urlopen(captured, body))

    reply = OllamaLLMClient(base_url="http://ollama:11434", model="qwen2.5:7b").generate_with_tools(ToolRequest(messages=_conversation(), tools=TOOLS))

    assert reply.tool_calls[0].name == "query_range" and reply.tool_calls[0].id.startswith("call_")
    assert captured["body"]["messages"][3] == {"role": "tool", "content": "flat at 0.2/s", "tool_name": "query_range"}


# --- JSON fallback -------------------------------------------------------------------------


class _ScriptedClient:
    """Only has generate(): answers with the scripted replies in order."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(content=self.replies.pop(0), model="scripted", provider="scripted")


def test_a_client_without_tool_calling_gets_the_json_fallback() -> None:
    client = _ScriptedClient('```json\n{"tool_calls": [{"name": "query_range", "arguments": {"promql": "up"}}]}\n```')

    reply = generate_with_tools(client, ToolRequest(messages=_conversation(), tools=TOOLS))

    assert [(call.name, call.arguments) for call in reply.tool_calls] == [("query_range", {"promql": "up"})]
    sent = client.requests[0]
    assert "query_range" in sent.messages[0].content and sent.response_format == "json"
    assert sent.messages[-1].content.startswith("Tool result for toolu_1 (query_range)")


def test_the_fallback_takes_a_final_answer_or_plain_text_as_done() -> None:
    final = JsonToolFallback(_ScriptedClient('{"final": {"summary": "Look at the database."}}')).generate_with_tools(ToolRequest(messages=_conversation(), tools=TOOLS))
    plain = JsonToolFallback(_ScriptedClient("I think it's the database.")).generate_with_tools(ToolRequest(messages=_conversation(), tools=TOOLS))

    assert final.tool_calls == () and json.loads(final.content) == {"summary": "Look at the database."}
    assert plain.tool_calls == () and plain.content == "I think it's the database."


def test_turns_survive_a_round_trip_through_json() -> None:
    turns = [*_conversation(), ToolTurn(role="assistant", raw=[{"type": "text", "text": "x"}], provider="anthropic", content="x")]

    assert [turn_from_dict(json.loads(json.dumps(turn_to_dict(turn)))) for turn in turns] == turns


def _http_error(code: int, error: str):
    import urllib.error

    return urllib.error.HTTPError("http://ollama:11434/api/chat", code, "Bad Request", {}, io.BytesIO(json.dumps({"error": error}).encode()))


def test_an_ollama_model_without_tool_calling_falls_back_to_json(monkeypatch) -> None:
    sent: list[dict] = []

    def urlopen(req, timeout=None):
        body = json.loads(req.data.decode("utf-8"))
        sent.append(body)
        if "tools" in body:
            raise _http_error(400, "registry.ollama.ai/library/gemma3:4b does not support tools")
        reply = {"message": {"role": "assistant", "content": json.dumps({"tool_calls": [{"name": "query_range", "arguments": {"promql": "up"}}]})}}
        return _FakeHTTPResponse(json.dumps(reply).encode("utf-8"))

    monkeypatch.setattr(ollama_provider.urllib.request, "urlopen", urlopen)
    reply = OllamaLLMClient(base_url="http://ollama:11434", model="gemma3:4b").generate_with_tools(ToolRequest(messages=_conversation(), tools=TOOLS))

    assert [(call.name, call.arguments) for call in reply.tool_calls] == [("query_range", {"promql": "up"})]
    assert "tools" not in sent[1] and sent[1]["format"] == "json"


def test_ollama_errors_say_what_ollama_said(monkeypatch) -> None:
    def urlopen(req, timeout=None):
        raise _http_error(404, 'model "qwen9" not found, try pulling it first')

    monkeypatch.setattr(ollama_provider.urllib.request, "urlopen", urlopen)
    client = OllamaLLMClient(base_url="http://ollama:11434", model="qwen9")

    with pytest.raises(LLMRequestError, match='Ollama returned HTTP 404: model "qwen9" not found'):
        client.generate_with_tools(ToolRequest(messages=_conversation(), tools=TOOLS))
    with pytest.raises(LLMRequestError, match="Ollama returned HTTP 404"):
        client.generate(LLMRequest(messages=[]))
