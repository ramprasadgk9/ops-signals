from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from backend.app.ai.exceptions import AIError
from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.interfaces import LLMRequest, LLMResponse
from backend.app.api import assistant as assistant_module
from backend.app.assistant.service import AssistantServices, OperationalIntelligenceAssistant
from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import FindingEntity


class _ScriptedClient:
    def __init__(self, *, response_text: str | None = None, raise_error: bool = False) -> None:
        self.response_text = response_text
        self.raise_error = raise_error
        self.calls: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if self.raise_error:
            raise AIError("boom")
        return LLMResponse(content=self.response_text or "")


def _assistant_with(client: _ScriptedClient) -> OperationalIntelligenceAssistant:
    services = AssistantServices(
        embedder=None,
        case_similarity=None,
        docs_store=None,
        ai_services=OptionalAIServices(client=client, structured=None),
    )
    return OperationalIntelligenceAssistant(services)


@pytest.fixture
def client_factory():
    created_apps = []

    def _make(*, assistant):
        app = create_app("sqlite+pysqlite:///:memory:")
        app.dependency_overrides[assistant_module.get_assistant] = lambda: assistant
        created_apps.append(app)
        return app

    yield _make


def _seed_finding(finding_id: int) -> None:
    session_local = get_session_local()
    with session_local() as db:
        db.add(
            FindingEntity(
                id=finding_id,
                analysis_run_id="run-ai-summary",
                service="checkout-api",
                metric_name="cpu_usage",
                title="CPU usage baseline shifted",
                summary="CPU moved from normal baseline to sustained high usage.",
                category="behavior_change",
                health_status="critical",
                importance_score=0.94,
                investigation_priority=1,
                signal_ids=["sig-1"],
                comparison_json={"comparison_type": "selected_window_split"},
                created_at=datetime.utcnow(),
            )
        )
        db.commit()


def test_finding_detail_has_no_ai_summary_when_assistant_is_unavailable(client_factory) -> None:
    app = client_factory(assistant=None)

    with TestClient(app) as client:
        _seed_finding(301)
        response = client.get("/api/findings/301")

    assert response.status_code == 200
    body = response.json()
    assert body["ai_summary"] is None
    assert body["summary"] == "CPU moved from normal baseline to sustained high usage."


def test_finding_detail_populates_and_caches_ai_summary_when_assistant_available(client_factory) -> None:
    fake_client = _ScriptedClient(response_text="CPU usage jumped and stayed high - worth a look.")
    assistant = _assistant_with(fake_client)
    app = client_factory(assistant=assistant)

    with TestClient(app) as client:
        _seed_finding(302)
        first = client.get("/api/findings/302")
        second = client.get("/api/findings/302")

    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["ai_summary"] == "CPU usage jumped and stayed high - worth a look."
    assert second.json()["ai_summary"] == "CPU usage jumped and stayed high - worth a look."
    assert first.json()["summary"] == "CPU moved from normal baseline to sustained high usage."
    # Cached after the first computation - second fetch must not call the LLM again.
    assert len(fake_client.calls) == 1


def test_finding_detail_falls_back_cleanly_when_ai_call_fails(client_factory) -> None:
    fake_client = _ScriptedClient(raise_error=True)
    assistant = _assistant_with(fake_client)
    app = client_factory(assistant=assistant)

    with TestClient(app) as client:
        _seed_finding(303)
        response = client.get("/api/findings/303")

    assert response.status_code == 200
    body = response.json()
    assert body["ai_summary"] is None
    assert body["summary"] == "CPU moved from normal baseline to sustained high usage."


def test_list_and_search_findings_are_unaffected_by_ai_summary_feature(client_factory) -> None:
    app = client_factory(assistant=None)

    with TestClient(app) as client:
        _seed_finding(304)
        list_response = client.get("/api/findings", params={"window": "24h"})
        search_response = client.get("/api/findings/search", params={"q": "cpu"})

    assert list_response.status_code == 200
    assert search_response.status_code == 200
    assert list_response.json()[0]["ai_summary"] is None
    assert search_response.json()[0]["ai_summary"] is None
