from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.app.ai.exceptions import AIError
from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.interfaces import LLMRequest, LLMResponse
from backend.app.ai.models import StructuredLLMService
from backend.app.api import assistant as assistant_module
from backend.app.assistant.service import AssistantServices, OperationalIntelligenceAssistant
from backend.app.main import create_app
from backend.app.metric_analyzer_recommendations.service import MetricAnalyzerRecommendationService
from backend.app.models.db import get_session_local
from backend.app.models.entities import NormalizedPoint


class _ScriptedClient:
    def __init__(self, *, response_json: dict | None = None, raise_error: bool = False) -> None:
        self.response_json = response_json
        self.raise_error = raise_error
        self.calls: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if self.raise_error:
            raise AIError("boom")
        return LLMResponse(content=json.dumps(self.response_json))


def _assistant_with(client: _ScriptedClient) -> OperationalIntelligenceAssistant:
    services = AssistantServices(
        embedder=None,
        case_similarity=None,
        docs_store=None,
        ai_services=OptionalAIServices(client=client, structured=StructuredLLMService(client, retry_on_invalid_output=False)),
    )
    return OperationalIntelligenceAssistant(services)


@pytest.fixture
def client_factory():
    created_apps = []

    def _make(*, assistant=None):
        app = create_app("sqlite+pysqlite:///:memory:")
        app.dependency_overrides[assistant_module.get_assistant] = lambda: assistant
        created_apps.append(app)
        return app

    yield _make


def _seed_trending_series(db_session_local, *, service_name: str = "checkout-service", metric_name: str = "memory_usage", analysis_run_id: str = "run-ai-opinion") -> None:
    with db_session_local() as db:
        start = datetime.utcnow() - timedelta(hours=2)
        for index in range(60):
            db.add(
                NormalizedPoint(
                    metric_name=metric_name,
                    timestamp=start + timedelta(minutes=index * 2),
                    value=100 + index * 0.5,
                    service=service_name,
                    analysis_run_id=analysis_run_id,
                )
            )
        db.commit()


def _discover_router_ground_truth(db_session_local) -> tuple[str, str, str]:
    """Returns (top_raw_analyzer_id, top_public_analyzer_id, another_eligible_raw_analyzer_id) by
    running the real deterministic router against the seeded dataset - avoids hardcoding an
    assumption about which analyzer the scoring formulas actually favor for this series shape."""
    probe = MetricAnalyzerRecommendationService()
    with db_session_local() as db:
        profile, timeseries = probe.profile_sample(db, "checkout-service", "memory_usage", "run-ai-opinion")
    # Same inputs the endpoint uses (the real series, not just the summary profile), so this
    # ground truth is the router's actual top pick for this sample.
    router_profile = probe._build_router_profile(profile, timeseries)
    decisions = probe._build_router().recommend_analyzers_for_profile(router_profile)
    eligible = [decision for decision in decisions if decision.eligible] or decisions
    top = max(eligible, key=lambda decision: decision.final_score)
    other = next(decision for decision in eligible if decision.analyzer != top.analyzer)
    return top.analyzer, probe._public_analyzer_id(top.analyzer), other.analyzer


def _evaluate(client: TestClient) -> dict:
    response = client.post(
        "/api/metric-analyzer-recommendations/evaluate",
        json={"service": "checkout-service", "metric_name": "memory_usage", "analysis_run_id": "run-ai-opinion"},
    )
    assert response.status_code == 200
    return response.json()


def test_ai_opinion_is_unavailable_and_recommendations_are_unaffected_when_assistant_is_missing(client_factory) -> None:
    app = client_factory(assistant=None)

    with TestClient(app) as client:
        _seed_trending_series(get_session_local())
        body = _evaluate(client)

    assert body["ai_opinion"]["available"] is False
    assert body["ai_opinion"]["unavailable_reason"]
    assert body["recommendations"]
    assert any(item["analyzer_id"] == "trend" for item in body["recommendations"])


def test_ai_opinion_populates_when_assistant_agrees_with_the_router(client_factory) -> None:
    fake_client = _ScriptedClient(response_json=None)
    app = client_factory(assistant=_assistant_with(fake_client))

    with TestClient(app) as client:
        _seed_trending_series(get_session_local())
        top_raw_id, top_public_id, _ = _discover_router_ground_truth(get_session_local())
        fake_client.response_json = {
            "best_analyzer_id": top_raw_id,
            "rationale": "This pick agrees with the router's own top-scored analyzer for this series shape.",
            "recommended": [
                {"analyzer_id": top_raw_id, "recommendation": "recommended", "rank": 1, "confidence": 0.9, "reason": "Rank 1, matches the router's top score."}
            ],
            "not_recommended": [],
            "caveats": [],
        }
        body = _evaluate(client)

    assert body["ai_opinion"]["available"] is True
    assert body["ai_opinion"]["best_analyzer_id"] == top_public_id
    assert body["ai_opinion"]["diverges_from_router"] is False
    assert body["ai_opinion"]["router_top_analyzer_id"] == top_public_id
    # The deterministic list must be unaffected by any of this - AI never touches it.
    assert any(item["analyzer_id"] == "trend" for item in body["recommendations"])


def test_ai_opinion_flags_divergence_from_the_router_without_changing_recommendations(client_factory) -> None:
    fake_client = _ScriptedClient(response_json=None)
    app = client_factory(assistant=_assistant_with(fake_client))

    with TestClient(app) as client:
        _seed_trending_series(get_session_local())
        top_raw_id, top_public_id, other_raw_id = _discover_router_ground_truth(get_session_local())
        fake_client.response_json = {
            "best_analyzer_id": other_raw_id,
            "rationale": "Evidence in the sample suggests a better fit than the router's top-scored pick, which this explicitly overrides with a reason.",
            "recommended": [
                {"analyzer_id": other_raw_id, "recommendation": "recommended", "rank": 1, "confidence": 0.7, "reason": "Rank 1, a better fit than the router's top score here."}
            ],
            "not_recommended": [],
            "caveats": ["Confirm with a longer window."],
        }
        body = _evaluate(client)

    assert body["ai_opinion"]["available"] is True
    assert body["ai_opinion"]["best_analyzer_id"] != top_public_id
    assert body["ai_opinion"]["router_top_analyzer_id"] == top_public_id
    assert body["ai_opinion"]["diverges_from_router"] is True
    # Divergence is surfaced as information only - it never overrides what recommend() decided.
    assert any(item["analyzer_id"] == "trend" for item in body["recommendations"])


def test_ai_opinion_falls_back_cleanly_when_the_advisor_call_fails(client_factory) -> None:
    fake_client = _ScriptedClient(raise_error=True)
    app = client_factory(assistant=_assistant_with(fake_client))

    with TestClient(app) as client:
        _seed_trending_series(get_session_local())
        body = _evaluate(client)

    assert body["ai_opinion"]["available"] is False
    assert body["ai_opinion"]["unavailable_reason"]
    assert any(item["analyzer_id"] == "trend" for item in body["recommendations"])


def test_ai_opinion_falls_back_cleanly_when_the_advisor_hallucinates_an_unknown_analyzer(client_factory) -> None:
    fake_client = _ScriptedClient(
        response_json={
            "best_analyzer_id": "not_a_real_analyzer",
            "rationale": "Fabricated.",
            "recommended": [
                {"analyzer_id": "not_a_real_analyzer", "recommendation": "recommended", "rank": 1, "confidence": 0.9, "reason": "Fabricated."}
            ],
            "not_recommended": [],
            "caveats": [],
        }
    )
    app = client_factory(assistant=_assistant_with(fake_client))

    with TestClient(app) as client:
        _seed_trending_series(get_session_local())
        body = _evaluate(client)

    assert body["ai_opinion"]["available"] is False
    assert any(item["analyzer_id"] == "trend" for item in body["recommendations"])
