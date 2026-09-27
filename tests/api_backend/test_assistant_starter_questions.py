"""Example questions on the Ask Ops Signals first screen, built from what this install has analysed."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.assistant.service import OperationalIntelligenceAssistant
from backend.app.assistant.starters import _shorten
from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import FindingEntity, OperationalCaseEntity

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def no_api_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPS_SIGNALS_API_TOKEN", raising=False)


@pytest.fixture()
def client() -> TestClient:
    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as test_client:
        yield test_client


def _finding(service: str | None, title: str, minutes_ago: int) -> FindingEntity:
    return FindingEntity(
        metric_name="error_rate", service=service, title=title, summary="s", category="anomaly", health_status="critical",
        created_at=NOW - timedelta(minutes=minutes_ago),
    )


def test_a_fresh_install_has_no_system_questions(client: TestClient) -> None:
    assert client.get("/api/assistant/starter-questions").json() == {"has_data": False, "questions": []}


def test_questions_name_the_busiest_service_newest_finding_and_newest_case(client: TestClient) -> None:
    with get_session_local()() as db:
        db.add_all([
            _finding("checkout-api", "CPU baseline shifted", 30),
            _finding("payments-api", "Error rate spiked on payments-api", 1),
            _finding("payments-api", "Latency up", 10),
            _finding(None, "Unlabelled series flatlined", 5),
            _finding("unknown", "Placeholder service one", 2),
            _finding("unknown", "Placeholder service two", 3),
            _finding("unknown", "Placeholder service three", 4),
        ])
        db.flush()
        db.add(OperationalCaseEntity(finding_id=1, analysis_run_id="run-1", case_title="Slow checkout after deploy v2.3", finding_snapshot={}))
        db.commit()

    body = client.get("/api/assistant/starter-questions").json()

    assert body == {
        "has_data": True,
        "questions": [
            "What changed recently on payments-api?",
            'Tell me about the finding "Error rate spiked on payments-api"',
            'Have we seen a case like "Slow checkout after deploy v2.3" before?',
            "Did any metric stop reporting?",
        ],
    }


def test_no_case_question_without_cases(client: TestClient) -> None:
    with get_session_local()() as db:
        db.add(_finding("checkout-api", "CPU baseline shifted", 1))
        db.commit()

    questions = client.get("/api/assistant/starter-questions").json()["questions"]

    assert not any("case" in question for question in questions)
    assert questions[0] == "What changed recently on checkout-api?"


def test_long_titles_are_cut_at_a_word() -> None:
    title = "Request latency p95 on checkout-api shifted upward after the 14:05 deploy and stayed elevated for hours"

    assert _shorten(title) == "Request latency p95 on checkout-api shifted upward after…"
    assert _shorten("Short title.") == "Short title"


@pytest.mark.parametrize(
    ("question", "route"),
    [
        ("What changed recently on payments-api?", "FINDING_SEARCH"),
        ('Tell me about the finding "Error rate spiked"', "FINDING_SEARCH"),
        ('Have we seen a case like "Slow checkout" before?', "CASE_SEARCH"),
        ("Did any metric stop reporting?", "FINDING_SEARCH"),
        ("Which behavior patterns were detected?", "BEHAVIOR_SEARCH"),
    ],
)
def test_each_question_reaches_the_search_for_its_evidence(question: str, route: str) -> None:
    assert route in OperationalIntelligenceAssistant.route_intents(question)
