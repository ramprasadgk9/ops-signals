from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.interfaces import LLMClient, LLMRequest, LLMResponse
from backend.app.ai.models import StructuredLLMService
from backend.app.api import assistant as assistant_module
from backend.app.assistant.service import AssistantServices, OperationalIntelligenceAssistant
from backend.app.main import create_app


class _ScriptedLLMClient(LLMClient):
    """Returns queued responses in order - one per generate() call."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        content = self._responses.pop(0) if self._responses else ""
        return LLMResponse(content=content, model="fake-model", provider="fake")


class _FakeEmbedder:
    def encode(self, text: str) -> list[float]:
        return [0.0]


class _FakeDocsStore:
    def __init__(self, results: list[dict]) -> None:
        self.results = results

    def search(self, vector, limit, score_threshold=None, filters=None):
        return self.results


_DOC_RESULT = {
    "score": 0.8,
    "payload": {
        "title": "What Are Analyzers?",
        "reference": "",
        "summary": "Analyzers inspect normalized metric time-series data.",
        "source_type": "generated",
    },
}


def test_llm_routing_adds_document_search_for_an_unrecognized_conceptual_question() -> None:
    # "Explain baseline shift" matches ANALYZER_SEARCH only - a real keyword category, not the
    # empty-match fallback (which now includes DOCUMENT_SEARCH itself, so it wouldn't exercise
    # this path). An LLM classifier that understands it's ALSO a documentation question should ADD
    # DOCUMENT_SEARCH on top of that keyword baseline - not replace it. Routing is additive: the
    # LLM can only broaden coverage, never narrow it, so a model that under-selects categories for
    # an obvious question can't silently lose evidence.
    from types import SimpleNamespace

    message = "Explain baseline shift"
    assert OperationalIntelligenceAssistant.route_intents(message) == ["ANALYZER_SEARCH"]

    client = _ScriptedLLMClient(["DOCUMENT_SEARCH", "Baseline shift is a sustained change in a metric's normal operating level."])
    ai_services = OptionalAIServices(client=client, structured=StructuredLLMService(client))
    assistant = OperationalIntelligenceAssistant(
        AssistantServices(
            embedder=_FakeEmbedder(),
            case_similarity=SimpleNamespace(vector_store=_FakeDocsStore([])),
            docs_store=_FakeDocsStore([_DOC_RESULT]),
            ai_services=ai_services,
        )
    )

    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[assistant_module.get_assistant] = lambda: assistant

    with TestClient(app) as test_client:
        response = test_client.post("/api/assistant/chat", json={"message": message, "top_k": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["routes"] == OperationalIntelligenceAssistant.route_intents(message) + ["DOCUMENT_SEARCH"]
    assert body["ai_synthesis_used"] is True
    # The model quoted nothing, so the answer carries the top document's own supporting passage.
    assert body["answer"].startswith("Baseline shift is a sustained change in a metric's normal operating level.\n\nFrom ")
    assert any(source["source_type"] == "app_documentation" for source in body["sources"])


def test_an_under_selecting_llm_does_not_drop_document_search_for_how_does_x_work_questions() -> None:
    # Regression test: a real local model (llama3.2) classified "How does Behavior Intelligence
    # work?" as BEHAVIOR_SEARCH only, dropping DOCUMENT_SEARCH that keyword routing reliably
    # catches via "how does". With zero real behavior-finding rows, that left zero evidence and
    # "I could not find strong operational evidence" for a question docs could answer fine.
    from types import SimpleNamespace

    client = _ScriptedLLMClient(["BEHAVIOR_SEARCH", "Behavior Intelligence combines signals across metrics."])
    ai_services = OptionalAIServices(client=client, structured=StructuredLLMService(client))
    assistant = OperationalIntelligenceAssistant(
        AssistantServices(
            embedder=_FakeEmbedder(),
            case_similarity=SimpleNamespace(vector_store=_FakeDocsStore([])),
            docs_store=_FakeDocsStore([_DOC_RESULT]),
            ai_services=ai_services,
        )
    )

    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[assistant_module.get_assistant] = lambda: assistant

    with TestClient(app) as test_client:
        response = test_client.post("/api/assistant/chat", json={"message": "How does Behavior Intelligence work?", "top_k": 3})

    assert response.status_code == 200
    body = response.json()
    assert "DOCUMENT_SEARCH" in body["routes"]
    assert any(source["source_type"] == "app_documentation" for source in body["sources"])
    assert body["knowledge_used"]


def test_routing_falls_back_to_keywords_when_the_llm_call_fails() -> None:
    from backend.app.ai.exceptions import LLMRequestError

    class _FailingClient(LLMClient):
        def generate(self, request: LLMRequest) -> LLMResponse:
            raise LLMRequestError("simulated failure")

    client = _FailingClient()
    ai_services = OptionalAIServices(client=client, structured=StructuredLLMService(client))
    assistant = OperationalIntelligenceAssistant(
        AssistantServices(embedder=_FakeEmbedder(), case_similarity=None, docs_store=_FakeDocsStore([]), ai_services=ai_services)
    )

    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[assistant_module.get_assistant] = lambda: assistant

    with TestClient(app) as test_client:
        response = test_client.post("/api/assistant/chat", json={"message": "What changed in checkout cpu?", "top_k": 3})

    assert response.status_code == 200
    body = response.json()
    # Same routes keyword routing would have produced for this message.
    assert body["routes"] == OperationalIntelligenceAssistant.route_intents("What changed in checkout cpu?")
