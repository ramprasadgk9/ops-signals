from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.api import memory as memory_module
from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import AnalysisRunEntity, BehaviorFindingEntity, OperationalCaseEntity


@pytest.fixture
def client_factory():
    created_apps = []

    def _make(*, indexer=None, config=None):
        app = create_app("sqlite+pysqlite:///:memory:")
        app.dependency_overrides[memory_module.get_memory_indexer] = lambda: indexer
        app.dependency_overrides[memory_module.get_memory_config] = lambda: config
        created_apps.append(app)
        return app

    yield _make


def _seed_behavior(db, *, behavior_id: int, analysis_run_id: str = "run-behavior-1") -> BehaviorFindingEntity:
    db.add(
        AnalysisRunEntity(
            id=analysis_run_id,
            source_type="prometheus",
            provider="prometheus",
            service="payments-service",
            metric_name="memory_usage",
            start_time=datetime.utcnow(),
            end_time=datetime.utcnow(),
            sample_count=100,
            status="completed",
            router_version="1.0",
            feature_extractor_version="1.0",
            analyzer_registry_version="1.0",
            series_profile_json={"sample_count": 100},
            router_decisions_json=[{"analyzer_id": "trend", "eligible": True}],
            executed_analyzers_json=[{"router_analyzer_id": "trend", "pipeline_analyzer_id": "trend", "execution_status": "completed"}],
            generated_findings_json=[],
        )
    )
    behavior = BehaviorFindingEntity(
        id=behavior_id,
        behavior_id=f"behavior-{behavior_id}",
        definition_id="memory_leak",
        definition_version=1,
        title="Memory leak driving resource degradation",
        summary="Sustained upward memory trend was accompanied by increased CPU throttling.",
        category="resource_constraint",
        severity="critical",
        service="payments-service",
        analysis_run_id=analysis_run_id,
        input_metrics_json={"memory": "memory_usage", "throttling": "cpu_throttled_seconds"},
        facts_json={"memory": {"trend": {"direction": "upward"}}},
        evidence_json=["memory.trend.direction", "throttling.baseline_shift.present"],
        matched_conditions_json=[{"fact": "memory.trend.direction", "operator": "equals", "value": "upward", "passed": True}],
        confidence=0.88,
        correlation_json={"strength": "strong"},
        occurrence_count=1,
        last_seen_at=datetime.utcnow(),
        created_at=datetime.utcnow(),
    )
    db.add(behavior)
    db.commit()
    db.refresh(behavior)
    return behavior


def test_creating_a_case_from_a_behavior_finding(client_factory) -> None:
    app = client_factory()

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            behavior = _seed_behavior(db, behavior_id=501)
            behavior_id = behavior.id

        response = client.post(f"/api/cases/behaviors/{behavior_id}/create")

    assert response.status_code == 200
    body = response.json()
    assert body["behavior_finding_id"] == behavior_id
    assert body["finding_id"] is None
    assert body["case_status"] == "open"

    with session_local() as db:
        case = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id == body["case_id"])).scalar_one()
        assert case.finding_id is None
        assert case.behavior_finding_id == behavior_id
        assert case.finding_snapshot["source_type"] == "behavior"
        assert case.finding_snapshot["service"] == "payments-service"
        assert case.finding_snapshot["metric_name"] == "memory_usage"
        assert case.finding_snapshot["metric_names"] == ["memory_usage", "cpu_throttled_seconds"]
        assert case.finding_snapshot["health_status"] == "critical"

        refreshed_behavior = db.execute(
            select(BehaviorFindingEntity).where(BehaviorFindingEntity.id == behavior_id)
        ).scalar_one()
        assert refreshed_behavior.case_id == case.id


def test_creating_a_case_from_behavior_twice_returns_the_existing_case(client_factory) -> None:
    app = client_factory()

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            behavior = _seed_behavior(db, behavior_id=502)
            behavior_id = behavior.id

        first = client.post(f"/api/cases/behaviors/{behavior_id}/create")
        second = client.post(f"/api/cases/behaviors/{behavior_id}/create")

    assert first.json()["case_id"] == second.json()["case_id"]

    with session_local() as db:
        count = len(db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.behavior_finding_id == behavior_id)).scalars().all())
    assert count == 1


def test_creating_a_case_from_a_missing_behavior_returns_404(client_factory) -> None:
    app = client_factory()

    with TestClient(app) as client:
        response = client.post("/api/cases/behaviors/9999/create")

    assert response.status_code == 404


def test_behavior_sourced_case_can_be_resolved_and_produces_a_learning_outcome(client_factory) -> None:
    app = client_factory()

    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            behavior = _seed_behavior(db, behavior_id=503)
            behavior_id = behavior.id

        case_id = client.post(f"/api/cases/behaviors/{behavior_id}/create").json()["case_id"]

        rca_response = client.patch(
            f"/api/cases/{case_id}/rca",
            json={
                "root_cause_status": "identified",
                "root_cause_summary": "Caching library leaked memory under load.",
                "root_cause_verified": True,
            },
        )
        assert rca_response.status_code == 200

        resolution_response = client.patch(
            f"/api/cases/{case_id}/resolution",
            json={
                "outcome_status": "resolved",
                "outcome_summary": "Upgraded caching library and redeployed.",
                "corrective_action": "Upgraded library to v2.3.",
                "learning_outcome_status": "confirmed",
                "root_cause_category": "memory_leak",
                "resolution_summary": "Upgraded caching library and redeployed.",
            },
        )

    assert resolution_response.status_code == 200
    assert resolution_response.json()["outcome_status"] == "resolved"

    outcomes_response_client = TestClient(app)
    outcomes = outcomes_response_client.get(
        "/api/learning-outcomes", params={"service_id": "payments-service", "metric_name": "memory_usage"}
    ).json()
    assert len(outcomes) == 1
    assert outcomes[0]["outcome_status"] == "confirmed"
    assert outcomes[0]["case_id"] == case_id
