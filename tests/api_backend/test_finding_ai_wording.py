"""AI wording on a finding's details: written once, checked against the facts, and the template
stays whenever AI is off, fails or writes something the facts don't support."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.ai.exceptions import AIError
from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.interfaces import LLMRequest, LLMResponse
from backend.app.api import assistant as assistant_module
from backend.app.assistant.service import AssistantServices, OperationalIntelligenceAssistant
from backend.app.main import create_app
from backend.app.config import MemoryConfig
from backend.app.models.db import get_session_local
from backend.app.models.entities import FindingEntity
from backend.app.services.finding_ai_wording import SYSTEM_PROMPT, check_line
from tests.api_backend.test_finding_plain_api import _seed

GOOD = {
    "why": "Fewer requests now fail, so most users get through again.",
    "check_extra": "Whether the fix that brought it down is still in place after the next release.",
    "related_extra": "Errors and slow requests dropping together often means a shared dependency recovered.",
}


class _Model:
    def __init__(self, reply: dict | str | None = None, *, fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail
        self.model = "test-model"
        self.calls: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if self.fail:
            raise AIError("model down")
        return LLMResponse(content=self.reply if isinstance(self.reply, str) else json.dumps(self.reply))


def _assistant(model: _Model | None) -> OperationalIntelligenceAssistant | None:
    if model is None:
        return None
    return OperationalIntelligenceAssistant(AssistantServices(embedder=None, case_similarity=None, docs_store=None, ai_services=OptionalAIServices(client=model, structured=None)))


@pytest.fixture()
def app_with():
    def _make(model: _Model | None) -> TestClient:
        with patch("backend.app.main.load_memory_config", return_value=MemoryConfig(enabled=False)):
            app = create_app("sqlite+pysqlite:///:memory:")
        app.dependency_overrides[assistant_module.get_assistant] = lambda: _assistant(model)
        client = TestClient(app)
        client.__enter__()
        now = datetime.now(timezone.utc)
        with get_session_local()() as db:
            _seed(db, 8300, now)
            _seed(db, 8299, now)
            _seed(db, 8306, now)
            db.add(FindingEntity(id=1, service="cart", metric_name="cpu_usage", title="cpu_usage has unusual behaviour.", summary="as stored", category="operational_insight",
                                 health_status="normal", importance_score=0.2, investigation_priority=3, signal_ids=[], comparison_json={}, created_at=now))
            db.commit()
        made.append(client)
        return client

    made: list[TestClient] = []
    yield _make
    for client in made:
        client.__exit__(None, None, None)


def test_ai_off_says_so_and_changes_nothing(app_with) -> None:
    client = app_with(None)
    assert client.get("/api/findings/8300/ai-wording").json() == {
        "available": False, "reason": "ai_off", "why": None, "check_extra": None, "related_extra": None, "model": None,
    }


def test_lines_are_written_once_and_saved(app_with) -> None:
    model = _Model(GOOD)
    client = app_with(model)
    first = client.get("/api/findings/8300/ai-wording").json()
    second = client.get("/api/findings/8300/ai-wording").json()
    # Error rate is a metric the wording file knows, so its why stays the template's.
    assert first == {**GOOD, "why": None, "available": True, "reason": None, "model": "test-model"}
    assert second == first
    assert len(model.calls) == 1


def test_the_model_gets_the_cards_facts_and_the_rules(app_with) -> None:
    model = _Model(GOOD)
    app_with(model).get("/api/findings/8300/ai-wording")
    system, user = model.calls[0].messages
    assert system.content == SYSTEM_PROMPT
    facts = json.loads(user.content)
    assert facts["metric_name"] == "error_rate"
    assert facts["service"] == "spike-lab"
    assert facts["headline"] == "Error rate dropped sharply and stayed lower"
    assert facts["related"] == "Slow-request time (p95) also dropped at Oct 19, 22:54 UTC (571 ms to 357 ms)."
    assert facts["write_why"] is False
    # Times read as UTC for the model; the markers never reach it.
    assert "[[time:" not in user.content


def test_a_metric_of_unknown_meaning_gets_its_why_written(app_with) -> None:
    model = _Model({"why": "This lab value may stand for work waiting in spike-lab, so a climb can mean a backlog.", "check_extra": None, "related_extra": None})
    body = app_with(model).get("/api/findings/8306/ai-wording").json()
    assert json.loads(model.calls[0].messages[1].content)["write_why"] is True
    assert body["why"] == "This lab value may stand for work waiting in spike-lab, so a climb can mean a backlog."


def test_a_line_with_a_made_up_number_keeps_the_template_and_the_others_stay(app_with) -> None:
    client = app_with(_Model({**GOOD, "check_extra": "Whether more than 40 requests a second still fail after the release."}))
    body = client.get("/api/findings/8300/ai-wording").json()
    assert body["check_extra"] is None
    assert body["related_extra"] == GOOD["related_extra"]


def test_a_failed_call_is_not_saved_so_the_next_open_tries_again(app_with) -> None:
    model = _Model(fail=True)
    client = app_with(model)
    assert client.get("/api/findings/8300/ai-wording").json()["reason"] == "failed"
    model.fail, model.reply = False, GOOD
    assert client.get("/api/findings/8300/ai-wording").json()["check_extra"] == GOOD["check_extra"]


def test_a_reply_that_is_not_json_counts_as_failed(app_with) -> None:
    client = app_with(_Model("Sure! Here is a nicer sentence."))
    assert client.get("/api/findings/8300/ai-wording").json()["reason"] == "failed"


def test_a_finding_without_plain_wording_gets_none(app_with) -> None:
    model = _Model(GOOD)
    assert app_with(model).get("/api/findings/1/ai-wording").json()["reason"] == "no_plain"
    assert model.calls == []


def test_unknown_finding_is_404(app_with) -> None:
    assert app_with(None).get("/api/findings/999/ai-wording").status_code == 404


def test_opening_a_plain_finding_no_longer_polishes_its_hidden_summary(app_with) -> None:
    model = _Model("A polished summary nobody would see.")
    body = app_with(model).get("/api/findings/8300").json()
    assert body["ai_summary"] is None
    assert model.calls == []


def test_a_finding_without_plain_wording_still_gets_its_ai_summary(app_with) -> None:
    model = _Model("CPU on cart looked unusual for a while.")
    assert app_with(model).get("/api/findings/1").json()["ai_summary"] == "CPU on cart looked unusual for a while."


FACTS = {
    "metric_name": "db_connections_active",
    "plain_name": "Active DB connections",
    "service": "payments",
    "headline": "Active DB connections got stuck at 100 for 42 min",
}


@pytest.mark.parametrize(
    ("line", "kept"),
    [
        ("The pool may be full at 100, so new payments can wait for a connection.", True),
        ("The db_connections_active metric may be at its limit for payments.", True),
        ("The pool may be full at 50 connections.", False),
        ("Check the redis_pool_size setting for payments.", False),
        ("This started after v2.3.1 rolled out to payments.", False),
        ("It got stuck at 2:06 PM when payments slowed down.", False),
        ("The root cause is the connection pool in payments.", False),
        ("This is a statistically unusual baseline for payments.", False),
        ("Pool full.", False),
        (" ".join(["word"] * 50), False),
        ("Check things, e.g. the pool size for payments.", True),
    ],
)
def test_check_line(line: str, kept: bool) -> None:
    assert (check_line(line, FACTS, None) is not None) is kept


def test_check_line_drops_a_copy_of_the_template() -> None:
    template = "Is the data source running and sending fresh values?"
    assert check_line("Is the data source running and sending fresh values now?", FACTS, template) is None
