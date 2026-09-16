from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import patch

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
from backend.app.models.entities import AnalyzerDivergenceEntity, NormalizedPoint


class _ScriptedClient:
    def __init__(self, *, response_json: dict | None = None, raise_error: bool = False) -> None:
        self.response_json = response_json
        self.raise_error = raise_error

    def generate(self, request: LLMRequest) -> LLMResponse:
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


def _seed_trending_series(db_session_local, *, service_name: str = "checkout-service", metric_name: str = "memory_usage", analysis_run_id: str = "run-divergence") -> None:
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
    probe = MetricAnalyzerRecommendationService()
    with db_session_local() as db:
        profile, _ = probe.profile_sample(db, "checkout-service", "memory_usage", "run-divergence")
    router_profile = probe._build_router_profile(profile)
    decisions = probe._build_router().recommend_analyzers_for_profile(router_profile)
    eligible = [decision for decision in decisions if decision.eligible] or decisions
    top = max(eligible, key=lambda decision: decision.final_score)
    other = next(decision for decision in eligible if decision.analyzer != top.analyzer)
    return top.analyzer, probe._public_analyzer_id(top.analyzer), other.analyzer


def _evaluate(client: TestClient) -> dict:
    response = client.post(
        "/api/metric-analyzer-recommendations/evaluate",
        json={"service": "checkout-service", "metric_name": "memory_usage", "analysis_run_id": "run-divergence"},
    )
    assert response.status_code == 200
    return response.json()


def _all_divergence_rows() -> list[AnalyzerDivergenceEntity]:
    from sqlalchemy import select

    with get_session_local()() as db:
        return db.execute(select(AnalyzerDivergenceEntity)).scalars().all()


def test_records_a_row_when_ai_agrees_with_the_router(client_factory) -> None:
    fake_client = _ScriptedClient(response_json=None)
    app = client_factory(assistant=_assistant_with(fake_client))

    with TestClient(app) as client:
        _seed_trending_series(get_session_local())
        top_raw_id, top_public_id, _ = _discover_router_ground_truth(get_session_local())
        fake_client.response_json = {
            "best_analyzer_id": top_raw_id,
            "rationale": "Agrees with the router's own top pick.",
            "recommended": [
                {"analyzer_id": top_raw_id, "recommendation": "recommended", "rank": 1, "confidence": 0.9, "reason": "Matches the router's top score."}
            ],
            "not_recommended": [],
            "caveats": [],
        }
        _evaluate(client)
        rows = _all_divergence_rows()

    assert len(rows) == 1
    row = rows[0]
    assert row.service == "checkout-service"
    assert row.metric_name == "memory_usage"
    assert row.analysis_run_id == "run-divergence"
    assert row.router_top_analyzer_id == top_public_id
    assert row.ai_top_analyzer_id == top_public_id
    assert row.diverged is False
    assert row.ai_confidence == pytest.approx(0.9)


def test_records_a_row_when_ai_diverges_from_the_router(client_factory) -> None:
    fake_client = _ScriptedClient(response_json=None)
    app = client_factory(assistant=_assistant_with(fake_client))

    with TestClient(app) as client:
        _seed_trending_series(get_session_local())
        top_raw_id, top_public_id, other_raw_id = _discover_router_ground_truth(get_session_local())
        fake_client.response_json = {
            "best_analyzer_id": other_raw_id,
            "rationale": "A better fit than the router's top pick here.",
            "recommended": [
                {"analyzer_id": other_raw_id, "recommendation": "recommended", "rank": 1, "confidence": 0.7, "reason": "Better fit."}
            ],
            "not_recommended": [],
            "caveats": [],
        }
        _evaluate(client)
        rows = _all_divergence_rows()

    assert len(rows) == 1
    row = rows[0]
    assert row.router_top_analyzer_id == top_public_id
    assert row.ai_top_analyzer_id != top_public_id
    assert row.diverged is True
    assert row.ai_confidence == pytest.approx(0.7)


def test_no_row_recorded_when_ai_is_unavailable(client_factory) -> None:
    app = client_factory(assistant=None)

    with TestClient(app) as client:
        _seed_trending_series(get_session_local())
        _evaluate(client)
        rows = _all_divergence_rows()

    assert rows == []


def test_no_row_recorded_when_the_advisor_call_fails(client_factory) -> None:
    fake_client = _ScriptedClient(raise_error=True)
    app = client_factory(assistant=_assistant_with(fake_client))

    with TestClient(app) as client:
        _seed_trending_series(get_session_local())
        _evaluate(client)
        rows = _all_divergence_rows()

    assert rows == []


def test_a_recording_failure_never_breaks_the_evaluate_response(client_factory) -> None:
    fake_client = _ScriptedClient(response_json=None)
    app = client_factory(assistant=_assistant_with(fake_client))

    with TestClient(app) as client:
        _seed_trending_series(get_session_local())
        top_raw_id, _, _ = _discover_router_ground_truth(get_session_local())
        fake_client.response_json = {
            "best_analyzer_id": top_raw_id,
            "rationale": "Agrees with the router.",
            "recommended": [
                {"analyzer_id": top_raw_id, "recommendation": "recommended", "rank": 1, "confidence": 0.9, "reason": "Matches."}
            ],
            "not_recommended": [],
            "caveats": [],
        }
        with patch(
            "backend.app.metric_analyzer_recommendations.api.AnalyzerDivergenceEntity",
            side_effect=RuntimeError("db is on fire"),
        ):
            body = _evaluate(client)

    assert body["ai_opinion"]["available"] is True
    assert _all_divergence_rows() == []


def test_list_divergences_filters_by_metric_service_and_diverged(client_factory) -> None:
    fake_client = _ScriptedClient(response_json=None)
    app = client_factory(assistant=_assistant_with(fake_client))

    with TestClient(app) as client:
        _seed_trending_series(get_session_local())
        top_raw_id, top_public_id, other_raw_id = _discover_router_ground_truth(get_session_local())
        fake_client.response_json = {
            "best_analyzer_id": other_raw_id,
            "rationale": "Diverges.",
            "recommended": [
                {"analyzer_id": other_raw_id, "recommendation": "recommended", "rank": 1, "confidence": 0.6, "reason": "Diverges."}
            ],
            "not_recommended": [],
            "caveats": [],
        }
        _evaluate(client)

        response = client.get(
            "/api/metric-analyzer-recommendations/divergences",
            params={"metric_name": "memory_usage", "service": "checkout-service", "diverged": True},
        )
        empty = client.get(
            "/api/metric-analyzer-recommendations/divergences",
            params={"metric_name": "memory_usage", "diverged": False},
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["diverged"] is True
    assert body[0]["router_top_analyzer_id"] == top_public_id

    assert empty.status_code == 200
    assert empty.json() == []
