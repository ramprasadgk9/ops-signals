"""Recorded AI answers (backend/app/ai/providers/recorded.py): recording from a real provider and
replaying for the hosted demo, where a new seed changes times, numbers and case ids."""

from __future__ import annotations

import json

import pytest

from backend.app.ai.config import AIConfig, apply_ai_env_overrides
from backend.app.ai.exceptions import LLMRequestError
from backend.app.ai.factory import build_llm_client, llm_client_issue
from backend.app.ai.interfaces import LLMMessage, LLMRequest, LLMResponse
from backend.app.ai.providers.recorded import RecordedLLMClient, RecordingLLMClient

RCA = "You draft a root-cause hypothesis for an on-call engineer from the case's facts only."


def _ask(user: str, system: str = RCA) -> LLMRequest:
    return LLMRequest(messages=[LLMMessage(role="system", content=system), LLMMessage(role="user", content=user)])


class _Model:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        return LLMResponse(content=self.reply, model="gemma3:4b", provider="ollama")


TODAY = "Finding on checkout-api: about 179 ms until Oct 30, 00:09 UTC, since then about 319 ms (up 78%). Change: deploy v2.14.0 at 00:05 UTC. Similar past case #1."
NEXT_RESET = "Finding on checkout-api: about 181 ms until Oct 30, 02:11 UTC, since then about 322 ms (up 77%). Change: deploy v2.14.0 at 02:07 UTC. Similar past case #1."


def test_an_answer_is_recorded_and_replayed_after_a_new_seed(tmp_path) -> None:
    path = tmp_path / "answers.json"
    model = _Model("Likely the per-item tax calculation in deploy v2.14.0.")
    recorder = RecordingLLMClient(model, path)
    assert recorder.generate(_ask(TODAY)).content == "Likely the per-item tax calculation in deploy v2.14.0."

    replay = RecordedLLMClient(path).generate(_ask(NEXT_RESET))
    assert replay.content == "Likely the per-item tax calculation in deploy v2.14.0."
    assert (replay.provider, replay.model) == ("recorded", "gemma3:4b")


def test_another_question_gets_no_recorded_answer(tmp_path) -> None:
    path = tmp_path / "answers.json"
    RecordingLLMClient(_Model("Likely the deploy."), path).generate(_ask(TODAY))
    client = RecordedLLMClient(path)

    with pytest.raises(LLMRequestError):
        client.generate(_ask("Finding on payments-db: waiting for a database connection went up. Similar past case #4."))
    # Same question asked by another feature (another system message): no answer either.
    with pytest.raises(LLMRequestError):
        client.generate(_ask(TODAY, system="You write the shift handoff note."))


def test_recording_the_same_question_again_replaces_it(tmp_path) -> None:
    path = tmp_path / "answers.json"
    RecordingLLMClient(_Model("First answer."), path).generate(_ask(TODAY))
    RecordingLLMClient(_Model("Second answer."), path).generate(_ask(NEXT_RESET))

    assert [entry["reply"] for entry in json.loads(path.read_text())] == ["Second answer."]
    assert RecordedLLMClient(path).generate(_ask(TODAY)).content == "Second answer."


def test_the_recorded_provider_comes_from_settings(tmp_path, monkeypatch) -> None:
    path = tmp_path / "answers.json"
    path.write_text("[]")
    monkeypatch.setenv("OPS_SIGNALS_AI_ENABLED", "true")
    monkeypatch.setenv("OPS_SIGNALS_AI_PROVIDER", "recorded")
    monkeypatch.setenv("OPS_SIGNALS_AI_RECORDED_FILE", str(path))
    config = apply_ai_env_overrides(AIConfig())

    assert llm_client_issue(config) is None
    assert isinstance(build_llm_client(config), RecordedLLMClient)
    monkeypatch.setenv("OPS_SIGNALS_AI_RECORDED_FILE", str(tmp_path / "missing.json"))
    assert "doesn't exist" in llm_client_issue(apply_ai_env_overrides(AIConfig()))


def test_record_to_wraps_the_real_provider(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPS_SIGNALS_AI_ENABLED", "true")
    monkeypatch.setenv("OPS_SIGNALS_AI_PROVIDER", "ollama")
    monkeypatch.setenv("OPS_SIGNALS_AI_RECORD_TO", str(tmp_path / "answers.json"))
    client = build_llm_client(apply_ai_env_overrides(AIConfig()))

    assert isinstance(client, RecordingLLMClient)
    assert client.model == "qwen2.5:3b"
