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
from backend.app.models.entities import BehaviorFindingEntity


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


def _seed_behavior_finding(finding_id: int) -> None:
    session_local = get_session_local()
    with session_local() as db:
        db.add(
            BehaviorFindingEntity(
                id=finding_id,
                behavior_id=f"behavior-{finding_id}",
                definition_id="server_slow_under_load",
                definition_version=1,
                title="Server slow under load",
                summary="Latency and CPU both rose together across the same window.",
                category="behavior",
                severity="high",
                service="checkout-api",
                analysis_run_id="run-behavior-ai",
                input_metrics_json={"latency_p99": "sig-1", "cpu_usage": "sig-2"},
                facts_json={"latency_p99": {"trend": "up"}, "cpu_usage": {"trend": "up"}},
                evidence_json=["latency_p99 trended up", "cpu_usage trended up"],
                matched_conditions_json=[{"fact": "latency_p99.trend", "operator": "eq", "value": "up", "passed": True}],
                confidence=0.82,
                correlation_json={"strength": "strong"},
                occurrence_count=1,
                last_seen_at=datetime.utcnow(),
                created_at=datetime.utcnow(),
            )
        )
        db.commit()


def test_behavior_findings_have_no_ai_explanation_when_assistant_is_unavailable(client_factory) -> None:
    app = client_factory(assistant=None)

    with TestClient(app) as client:
        _seed_behavior_finding(401)
        response = client.get("/api/behavior-evaluations")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["ai_explanation"] is None
    assert body[0]["summary"] == "Latency and CPU both rose together across the same window."


def test_behavior_findings_populate_and_cache_ai_explanation_when_assistant_available(client_factory) -> None:
    fake_client = _ScriptedClient(response_text="Latency rose alongside CPU, suggesting load-driven slowdown.")
    assistant = _assistant_with(fake_client)
    app = client_factory(assistant=assistant)

    with TestClient(app) as client:
        _seed_behavior_finding(402)
        first = client.get("/api/behavior-evaluations")
        second = client.get("/api/behavior-evaluations")

    assert first.status_code == 200 and second.status_code == 200
    assert first.json()[0]["ai_explanation"] == "Latency rose alongside CPU, suggesting load-driven slowdown."
    assert second.json()[0]["ai_explanation"] == "Latency rose alongside CPU, suggesting load-driven slowdown."
    assert first.json()[0]["summary"] == "Latency and CPU both rose together across the same window."
    assert len(fake_client.calls) == 1


def test_behavior_findings_fall_back_cleanly_when_ai_call_fails(client_factory) -> None:
    fake_client = _ScriptedClient(raise_error=True)
    assistant = _assistant_with(fake_client)
    app = client_factory(assistant=assistant)

    with TestClient(app) as client:
        _seed_behavior_finding(403)
        response = client.get("/api/behavior-evaluations")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["ai_explanation"] is None
    assert body[0]["summary"] == "Latency and CPU both rose together across the same window."
    assert body[0]["facts_json"] == {"latency_p99": {"trend": "up"}, "cpu_usage": {"trend": "up"}}


class _SlowClient(_ScriptedClient):
    """A model that takes `seconds` per answer, on a fake clock."""

    def __init__(self, clock: list[float], seconds: float) -> None:
        super().__init__(response_text="Both metrics went up together.")
        self.clock = clock
        self.seconds = seconds

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.clock[0] += self.seconds
        return super().generate(request)


def test_the_list_stops_writing_explanations_after_its_budget_and_writes_the_rest_later(client_factory, monkeypatch) -> None:
    # A local model takes seconds per explanation; the list used to wait for all of them.
    clock = [1000.0]
    monkeypatch.setattr("backend.app.api.behavior_evaluations.time.monotonic", lambda: clock[0])
    fake_client = _SlowClient(clock, seconds=3.0)
    app = client_factory(assistant=_assistant_with(fake_client))

    with TestClient(app) as client:
        for finding_id in (411, 412, 413, 414):
            _seed_behavior_finding(finding_id)
        first = client.get("/api/behavior-evaluations").json()
        second = client.get("/api/behavior-evaluations").json()

    # 3 s each against a 5 s budget: two the first time, the other two on the next load.
    assert sum(1 for row in first if row["ai_explanation"]) == 2
    assert all(row["ai_explanation"] for row in second)
    assert len(fake_client.calls) == 4
