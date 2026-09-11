from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from backend.app.ai.exceptions import LLMRequestError
from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.interfaces import LLMClient, LLMRequest, LLMResponse
from backend.app.ai.models import StructuredLLMService
from backend.app.api import assistant as assistant_module
from backend.app.assistant.service import AssistantServices, OperationalIntelligenceAssistant
from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import FindingEntity


class _FakeLLMClient(LLMClient):
    def __init__(self, *, response: str | None = None, should_fail: bool = False) -> None:
        self.response = response
        self.should_fail = should_fail
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self.should_fail:
            raise LLMRequestError("simulated LLM failure")
        return LLMResponse(content=self.response or "", model="fake-model", provider="fake")


def _assistant_with(client: LLMClient | None) -> OperationalIntelligenceAssistant:
    ai_services = OptionalAIServices(client=client, structured=StructuredLLMService(client)) if client else None
    return OperationalIntelligenceAssistant(
        AssistantServices(embedder=None, case_similarity=None, docs_store=None, ai_services=ai_services)
    )


def _seed_finding(db, finding_id: int) -> None:
    db.add(
        FindingEntity(
            id=finding_id,
            analysis_run_id="run-assistant-llm",
            service="checkout-api",
            metric_name="cpu_usage",
            title="CPU usage baseline shifted",
            summary="CPU moved from normal baseline to sustained high usage.",
            category="behavior_change",
            health_status="critical",
            importance_score=0.9,
            investigation_priority=1,
            signal_ids=["sig-1"],
            comparison_json={},
            created_at=datetime.utcnow(),
        )
    )
    db.commit()


def test_chat_uses_llm_synthesis_when_ai_is_enabled_and_evidence_found() -> None:
    fake_client = _FakeLLMClient(response="CPU usage on checkout-api shifted to a new baseline, per the finding evidence.")
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[assistant_module.get_assistant] = lambda: _assistant_with(fake_client)

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_finding(db, finding_id=301)

        response = client.post("/api/assistant/chat", json={"message": "What changed in checkout cpu?", "top_k": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["ai_synthesis_used"] is True
    assert body["answer"] == "CPU usage on checkout-api shifted to a new baseline, per the finding evidence."
    # One call classifies routes, one synthesizes the final answer from evidence.
    assert len(fake_client.requests) == 2
    assert "Evidence:" in fake_client.requests[-1].messages[-1].content


def test_chat_falls_back_to_template_when_llm_call_fails() -> None:
    fake_client = _FakeLLMClient(should_fail=True)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[assistant_module.get_assistant] = lambda: _assistant_with(fake_client)

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_finding(db, finding_id=302)

        response = client.post("/api/assistant/chat", json={"message": "What changed in checkout cpu?", "top_k": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["ai_synthesis_used"] is False
    assert body["answer"].startswith("Summary")


def test_chat_never_calls_llm_when_no_evidence_is_found() -> None:
    fake_client = _FakeLLMClient(response="should never be used")
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[assistant_module.get_assistant] = lambda: _assistant_with(fake_client)

    with TestClient(app) as client:
        response = client.post("/api/assistant/chat", json={"message": "What changed in an unknown metric?", "top_k": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["ai_synthesis_used"] is False
    # Route classification still runs, but no evidence means synthesis must be skipped.
    assert all("Evidence:" not in request.messages[-1].content for request in fake_client.requests)


def test_chat_uses_template_when_ai_is_disabled() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[assistant_module.get_assistant] = lambda: _assistant_with(None)

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_finding(db, finding_id=303)

        response = client.post("/api/assistant/chat", json={"message": "What changed in checkout cpu?", "top_k": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["ai_synthesis_used"] is False
    assert body["answer"].startswith("Summary")
