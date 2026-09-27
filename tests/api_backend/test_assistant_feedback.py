"""Thumbs up / down on Ask Ops Signals answers, and the flagged-question list the Docs check page reads."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app


@pytest.fixture(autouse=True)
def no_api_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPS_SIGNALS_API_TOKEN", raising=False)


@pytest.fixture()
def client() -> TestClient:
    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as test_client:
        yield test_client


def _down(client: TestClient, question: str, cited: list[str] | None = None) -> dict:
    response = client.post("/api/assistant/feedback", json={"question": question, "helpful": False, "cited": cited or []})
    assert response.status_code == 201
    return response.json()


def test_a_thumbs_down_gets_its_reason_afterwards(client: TestClient) -> None:
    created = _down(client, "How do I rotate the API token?")

    updated = client.patch(f"/api/assistant/feedback/{created['id']}", json={"reason": "wrong_section"}).json()

    assert created["reason"] is None
    assert updated["reason"] == "wrong_section" and updated["status"] == "open"


def test_flagged_questions_group_the_same_question_however_it_was_typed(client: TestClient) -> None:
    first = _down(client, "how do i rotate the api token", ["docs/security-model.md#whats-open-by-default"])
    client.patch(f"/api/assistant/feedback/{first['id']}", json={"reason": "wrong_section"})
    second = _down(client, "How do I rotate the  API token?", ["docs/security-model.md#whats-open-by-default"])
    client.patch(f"/api/assistant/feedback/{second['id']}", json={"reason": "wrong_section"})
    _down(client, "where is the helm chart")
    client.post("/api/assistant/feedback", json={"question": "What port does the UI use?", "helpful": True})

    flagged = client.get("/api/assistant/feedback/flagged").json()

    assert [item["question"] for item in flagged] == ["How do I rotate the  API token?", "where is the helm chart"]
    assert flagged[0]["count"] == 2
    assert flagged[0]["reasons"] == {"wrong_section": 2}
    assert flagged[0]["cited"] == ["docs/security-model.md#whats-open-by-default"]
    assert sorted(flagged[0]["feedback_ids"]) == sorted([first["id"], second["id"]])


def test_a_handled_question_leaves_the_flagged_list(client: TestClient) -> None:
    created = _down(client, "where is the helm chart")

    client.patch(f"/api/assistant/feedback/{created['id']}", json={"status": "dismissed"})

    assert client.get("/api/assistant/feedback/flagged").json() == []


def test_a_thumbs_up_never_carries_a_reason(client: TestClient) -> None:
    created = client.post("/api/assistant/feedback", json={"question": "q", "helpful": True, "reason": "outdated"}).json()

    assert created["reason"] is None
    assert client.patch(f"/api/assistant/feedback/{created['id']}", json={"reason": "outdated"}).json()["reason"] is None


def test_unknown_feedback_and_reasons_are_rejected(client: TestClient) -> None:
    assert client.patch("/api/assistant/feedback/999", json={"reason": "outdated"}).status_code == 404
    assert client.post("/api/assistant/feedback", json={"question": "q", "helpful": False, "reason": "boring"}).status_code == 422
