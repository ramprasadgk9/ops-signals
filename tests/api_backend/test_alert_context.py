from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.ai.exceptions import AIError
from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.interfaces import LLMRequest, LLMResponse
from backend.app.api import assistant as assistant_module
from backend.app.api import memory as memory_module
from backend.app.assistant.service import AssistantServices, OperationalIntelligenceAssistant
from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import AnalyzerLearningOutcomeEntity, BehaviorFindingEntity, FindingEntity, OperationalCaseEntity


class _FakeVectorSearch:
    def __init__(self, results: list[dict]) -> None:
        self.results = results
        self.calls: list[dict] = []

    def search(self, vector, filters=None, limit=5, score_threshold=0.0, **_kwargs):
        self.calls.append({"filters": filters, "limit": limit, "score_threshold": score_threshold})
        return self.results


class _FakeEmbedder:
    def encode(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class _ScriptedLLMClient:
    def __init__(self, *, response_text: str | None = None, raise_error: bool = False) -> None:
        self.response_text = response_text
        self.raise_error = raise_error
        self.calls: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if self.raise_error:
            raise AIError("boom")
        return LLMResponse(content=self.response_text or "")


def _assistant_with_ai(client: _ScriptedLLMClient) -> OperationalIntelligenceAssistant:
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

    def _make(*, similarity=None, embedder=None, assistant=None):
        app = create_app("sqlite+pysqlite:///:memory:")
        app.dependency_overrides[memory_module.get_similarity_service] = lambda: similarity
        app.dependency_overrides[memory_module.get_embedder] = lambda: embedder
        app.dependency_overrides[assistant_module.get_assistant] = lambda: assistant
        created_apps.append(app)
        return app

    yield _make


def _seed_outcome(
    db,
    *,
    outcome_id: str,
    metric_name: str = "cpu_usage",
    service_id: str | None = "payments-service",
    outcome_status: str = "confirmed",
    root_cause_category: str | None = "cpu_throttling",
    resolution_summary: str | None = "Increased CPU limit.",
    case_id: int = 1,
    created_at: datetime | None = None,
) -> None:
    db.add(
        AnalyzerLearningOutcomeEntity(
            id=outcome_id,
            service_id=service_id,
            metric_name=metric_name,
            analysis_run_id=f"run-{outcome_id}",
            case_id=case_id,
            series_profile={},
            router_decisions=[],
            executed_analyzers=[],
            outcome_status=outcome_status,
            root_cause_category=root_cause_category,
            resolution_summary=resolution_summary,
            confirmed_analyzers=["anomaly_zscore"] if outcome_status == "confirmed" else [],
            rejected_analyzers=[] if outcome_status == "confirmed" else ["anomaly_zscore"],
            created_at=created_at or datetime.utcnow(),
        )
    )
    db.commit()


def _seed_case(db, *, case_id: int, finding_id: int) -> None:
    db.add(
        OperationalCaseEntity(
            id=case_id,
            finding_id=finding_id,
            analysis_run_id="run-case",
            case_title="CPU throttling on payments-service",
            case_status="resolved",
            finding_snapshot={"service": "payments-service", "metric_name": "cpu_usage"},
            root_cause_summary="Sustained CPU usage anomaly correlated with rising throttled_seconds.",
            outcome_status="confirmed",
            outcome_summary="Increased CPU limit; throttling stopped.",
        )
    )
    db.commit()


def test_no_prior_history_and_no_message_returns_insufficient_history(client_factory) -> None:
    app = client_factory(similarity=None, embedder=None)

    with TestClient(app) as client:
        response = client.get("/api/alert-context", params={"metric_name": "cpu_usage", "service": "payments-service"})

    assert response.status_code == 200
    body = response.json()
    assert body["history"]["total_prior_occurrences"] == 0
    assert body["exact_match_outcomes"] == []
    assert body["similar_cases"] == []
    assert body["recommendation"] == "insufficient_history"


def test_mostly_confirmed_history_recommends_likely_real(client_factory) -> None:
    app = client_factory(similarity=None, embedder=None)

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_outcome(db, outcome_id="o1", outcome_status="confirmed", case_id=1)
            _seed_outcome(db, outcome_id="o2", outcome_status="confirmed", case_id=2)
            _seed_outcome(db, outcome_id="o3", outcome_status="rejected", case_id=3)

        response = client.get("/api/alert-context", params={"metric_name": "cpu_usage", "service": "payments-service"})

    assert response.status_code == 200
    body = response.json()
    assert body["history"]["total_prior_occurrences"] == 3
    assert body["history"]["confirmed"] == 2
    assert body["history"]["rejected"] == 1
    assert body["history"]["confirmed_rate"] == pytest.approx(2 / 3)
    assert body["history"]["most_common_root_cause"] == "cpu_throttling"
    assert body["recommendation"] == "likely_real"
    assert len(body["exact_match_outcomes"]) == 3


def test_mostly_rejected_history_recommends_likely_noise(client_factory) -> None:
    app = client_factory(similarity=None, embedder=None)

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_outcome(db, outcome_id="o1", outcome_status="rejected", case_id=1)
            _seed_outcome(db, outcome_id="o2", outcome_status="rejected", case_id=2)
            _seed_outcome(db, outcome_id="o3", outcome_status="rejected", case_id=3)
            _seed_outcome(db, outcome_id="o4", outcome_status="confirmed", case_id=4)

        response = client.get("/api/alert-context", params={"metric_name": "cpu_usage", "service": "payments-service"})

    assert response.status_code == 200
    body = response.json()
    assert body["recommendation"] == "likely_noise"


def test_outcomes_scoped_to_the_requested_service_only(client_factory) -> None:
    app = client_factory(similarity=None, embedder=None)

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_outcome(db, outcome_id="o1", service_id="payments-service", outcome_status="confirmed", case_id=1)
            _seed_outcome(db, outcome_id="o2", service_id="checkout-api", outcome_status="rejected", case_id=2)

        response = client.get("/api/alert-context", params={"metric_name": "cpu_usage", "service": "payments-service"})

    assert response.status_code == 200
    body = response.json()
    assert body["history"]["total_prior_occurrences"] == 1
    assert body["history"]["confirmed"] == 1


def test_message_triggers_semantic_search_for_similar_cases(client_factory) -> None:
    fake_results = [
        {
            "score": 0.86,
            "payload": {"case_id": 42, "service": "payments-service", "metric_name": "cpu_usage"},
        }
    ]
    similarity = SimpleNamespace(vector_store=_FakeVectorSearch(fake_results))
    app = client_factory(similarity=similarity, embedder=_FakeEmbedder())

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_case(db, case_id=42, finding_id=1)

        response = client.get(
            "/api/alert-context",
            params={
                "metric_name": "cpu_usage",
                "service": "payments-service",
                "message": "CPU usage spike on payments-service, threshold 85% breached",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["similar_cases"]) == 1
    match = body["similar_cases"][0]
    assert match["case_id"] == 42
    assert match["similarity_score"] == pytest.approx(0.86)
    assert match["reference"] == "/cases/42"
    assert similarity.vector_store.calls[0]["filters"] == {
        "must": [
            # Imported incidents have no metric, so they match on service alone.
            {
                "should": [
                    {"key": "metric_name", "match": {"value": "cpu_usage"}},
                    {"key": "origin", "match": {"value": "imported"}},
                ]
            },
            {"key": "service", "match": {"value": "payments-service"}},
        ]
    }


def test_similar_case_found_with_no_exact_match_history_is_not_reported_as_mixed(client_factory) -> None:
    fake_results = [
        {
            "score": 0.37,
            "payload": {"case_id": 9, "service": "trend-lab", "metric_name": "ops_signal_lab_value"},
        }
    ]
    similarity = SimpleNamespace(vector_store=_FakeVectorSearch(fake_results))
    app = client_factory(similarity=similarity, embedder=_FakeEmbedder())

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_case(db, case_id=9, finding_id=1)

        response = client.get(
            "/api/alert-context",
            params={"metric_name": "ops_signal_lab_value", "service": "trend-lab", "message": "baseline shift"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["history"]["total_prior_occurrences"] == 0
    assert len(body["similar_cases"]) == 1
    assert body["recommendation"] == "insufficient_history"
    assert "mixed" not in body["recommendation_basis"]
    assert body["recommendation_basis"].startswith("Seen before: 1 similar past incident, no real-vs-noise verdict yet.")
    assert "Fixed by: Increased CPU limit" in body["recommendation_basis"]
    assert ". Fixed by:" in body["recommendation_basis"]


def _seed_finding(
    db, *, finding_id: int, metric_name: str = "cpu_usage", service: str = "payments-service", title: str | None = None
) -> None:
    db.add(
        FindingEntity(
            id=finding_id,
            analysis_run_id=f"run-finding-{finding_id}",
            service=service,
            metric_name=metric_name,
            title=title or f"{metric_name} anomaly on {service}",
            summary="Metric moved outside its normal range.",
            category="behavior_change",
            health_status="critical",
            importance_score=0.8,
            investigation_priority=1,
            signal_ids=[],
            comparison_json={},
            created_at=datetime.utcnow(),
        )
    )
    db.commit()


def _seed_uncased_behavior(db, *, behavior_id: int, metric_name: str = "cpu_usage", service: str = "payments-service") -> None:
    db.add(
        BehaviorFindingEntity(
            id=behavior_id,
            behavior_id=f"behavior-{behavior_id}",
            definition_id="cpu_throttling",
            definition_version=1,
            title=f"Possible issue on {service}",
            summary="Correlated conditions matched.",
            category="resource_constraint",
            severity="high",
            service=service,
            input_metrics_json={"primary": metric_name, "secondary": "cpu_throttled_seconds"},
            facts_json={},
            evidence_json=["primary.trend.direction"],
            matched_conditions_json=[],
            confidence=0.75,
            correlation_json={},
            occurrence_count=1,
            last_seen_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
        )
    )
    db.commit()


def test_raw_activity_counts_uncased_findings_and_behaviors(client_factory) -> None:
    app = client_factory(similarity=None, embedder=None)

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_finding(db, finding_id=1, metric_name="cpu_usage", service="payments-service", title="CPU baseline shifted upward")
            _seed_finding(db, finding_id=2, metric_name="cpu_usage", service="payments-service", title="CPU trend regression detected")
            _seed_uncased_behavior(db, behavior_id=1, metric_name="cpu_usage", service="payments-service")

        response = client.get("/api/alert-context", params={"metric_name": "cpu_usage", "service": "payments-service"})

    assert response.status_code == 200
    body = response.json()
    assert body["raw_activity"]["finding_count"] == 2
    assert body["raw_activity"]["behavior_count"] == 1
    assert body["raw_activity"]["total_occurrences"] == 3
    assert len(body["raw_activity"]["recent_titles"]) == 3
    # Raw occurrence alone must never upgrade the recommendation - no outcome was ever recorded.
    assert body["recommendation"] == "insufficient_history"


def test_raw_activity_deduplicates_repeated_titles_but_keeps_true_counts(client_factory) -> None:
    app = client_factory(similarity=None, embedder=None)

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            # Repeated analysis runs on the same data produce new rows with byte-identical,
            # deterministically-generated titles - this must not print the same sentence 3 times.
            _seed_finding(db, finding_id=30, metric_name="cpu_usage", service="payments-service", title="CPU baseline shifted upward")
            _seed_finding(db, finding_id=31, metric_name="cpu_usage", service="payments-service", title="CPU baseline shifted upward")
            _seed_finding(db, finding_id=32, metric_name="cpu_usage", service="payments-service", title="CPU baseline shifted upward")
            _seed_finding(db, finding_id=33, metric_name="cpu_usage", service="payments-service", title="CPU trend regression detected")

        response = client.get("/api/alert-context", params={"metric_name": "cpu_usage", "service": "payments-service"})

    assert response.status_code == 200
    body = response.json()
    # True occurrence count is unaffected by dedup - "this happened 4 times" is still accurate.
    assert body["raw_activity"]["finding_count"] == 4
    assert body["raw_activity"]["total_occurrences"] == 4
    # But only distinct titles are shown, most-recent first (finding 33 was seeded last).
    assert body["raw_activity"]["recent_titles"] == ["CPU trend regression detected", "CPU baseline shifted upward"]


def test_recommendation_basis_mentions_raw_activity_instead_of_claiming_nothing_found(client_factory) -> None:
    app = client_factory(similarity=None, embedder=None)

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_finding(db, finding_id=10, metric_name="cpu_usage", service="payments-service")

        response = client.get("/api/alert-context", params={"metric_name": "cpu_usage", "service": "payments-service"})

    body = response.json()
    assert body["recommendation"] == "insufficient_history"
    assert "occurred" in body["recommendation_basis"]
    assert "1 time(s)" in body["recommendation_basis"]


def test_raw_activity_scoped_by_service_and_metric(client_factory) -> None:
    app = client_factory(similarity=None, embedder=None)

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_finding(db, finding_id=3, metric_name="cpu_usage", service="payments-service")
            _seed_finding(db, finding_id=4, metric_name="cpu_usage", service="checkout-api")
            _seed_uncased_behavior(db, behavior_id=2, metric_name="memory_usage", service="payments-service")

        response = client.get("/api/alert-context", params={"metric_name": "cpu_usage", "service": "payments-service"})

    assert response.status_code == 200
    body = response.json()
    assert body["raw_activity"]["finding_count"] == 1
    assert body["raw_activity"]["behavior_count"] == 0
    assert body["raw_activity"]["total_occurrences"] == 1


def test_raw_activity_gets_an_ai_summary_when_ai_is_available(client_factory) -> None:
    llm_client = _ScriptedLLMClient(response_text="This service has repeatedly shown baseline and trend shifts, but nothing has ever been confirmed or resolved.")
    app = client_factory(similarity=None, embedder=None, assistant=_assistant_with_ai(llm_client))

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_finding(db, finding_id=20, metric_name="cpu_usage", service="payments-service")
            _seed_finding(db, finding_id=21, metric_name="cpu_usage", service="payments-service")

        response = client.get("/api/alert-context", params={"metric_name": "cpu_usage", "service": "payments-service"})

    assert response.status_code == 200
    body = response.json()
    assert body["raw_activity"]["ai_summary"] == (
        "This service has repeatedly shown baseline and trend shifts, but nothing has ever been confirmed or resolved."
    )
    # Deterministic fields must still be present alongside the AI summary, never replaced by it.
    assert body["raw_activity"]["finding_count"] == 2
    assert body["raw_activity"]["recent_titles"]

    request = llm_client.calls[0]
    evidence = request.messages[-1].content
    assert "cpu_usage" in evidence
    assert "payments-service" in evidence


def test_raw_activity_ai_summary_is_none_when_ai_is_unavailable(client_factory) -> None:
    app = client_factory(similarity=None, embedder=None, assistant=None)

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_finding(db, finding_id=22, metric_name="cpu_usage", service="payments-service")

        response = client.get("/api/alert-context", params={"metric_name": "cpu_usage", "service": "payments-service"})

    body = response.json()
    assert body["raw_activity"]["ai_summary"] is None
    assert body["raw_activity"]["finding_count"] == 1


def test_raw_activity_ai_summary_failure_falls_back_to_none(client_factory) -> None:
    llm_client = _ScriptedLLMClient(raise_error=True)
    app = client_factory(similarity=None, embedder=None, assistant=_assistant_with_ai(llm_client))

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            _seed_finding(db, finding_id=23, metric_name="cpu_usage", service="payments-service")

        response = client.get("/api/alert-context", params={"metric_name": "cpu_usage", "service": "payments-service"})

    assert response.status_code == 200
    assert response.json()["raw_activity"]["ai_summary"] is None


def test_message_ignored_when_memory_services_not_initialized(client_factory) -> None:
    app = client_factory(similarity=None, embedder=None)

    with TestClient(app) as client:
        response = client.get(
            "/api/alert-context",
            params={"metric_name": "cpu_usage", "message": "anything"},
        )

    assert response.status_code == 200
    assert response.json()["similar_cases"] == []
