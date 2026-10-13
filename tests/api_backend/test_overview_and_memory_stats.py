from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.models.db import get_db, get_session_local
from backend.app.models.entities import BehaviorFindingEntity, FindingEntity, OperationalCaseEntity
from backend.app.api import memory as memory_api


def _finding(finding_id: int, service: str, severity: str, category: str, created_at: datetime) -> FindingEntity:
    return FindingEntity(
        id=finding_id,
        analysis_run_id="run-1",
        service=service,
        metric_name="cpu_usage",
        title=f"Finding {finding_id}",
        summary="finding summary",
        category=category,
        health_status=severity,
        importance_score=0.9,
        investigation_priority=1,
        signal_ids=[],
        comparison_json={},
        created_at=created_at,
    )


def _case(case_id: int, finding_id: int, status: str, outcome_status: str, memory_status: str, created_at: datetime) -> OperationalCaseEntity:
    return OperationalCaseEntity(
        id=case_id,
        finding_id=finding_id,
        analysis_run_id="run-1",
        case_title=f"Case {case_id}",
        case_status=status,
        finding_snapshot={"metric_name": "cpu_usage", "service": "checkout-api"},
        investigation_status="in_progress",
        investigation_notes=[],
        root_cause_status="unknown",
        root_cause_verified=False,
        outcome_status=outcome_status,
        memory_status=memory_status,
        created_at=created_at,
        updated_at=created_at,
    )


def test_overview_summary_aggregates_from_existing_tables() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    now = datetime.utcnow()
    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            db.add_all(
                [
                    _finding(1, "checkout-api", "critical", "behavior_change", now - timedelta(hours=2)),
                    _finding(2, "payments-api", "high", "anomaly", now - timedelta(hours=1)),
                    _finding(3, "inventory-api", "low", "trend", now - timedelta(days=3)),
                    _case(1, 1, "resolved", "resolved", "indexed", now - timedelta(hours=2)),
                    _case(2, 2, "open", "pending", "not_indexed", now - timedelta(hours=1)),
                    BehaviorFindingEntity(
                        behavior_id="cpu-saturation",
                        definition_id="cpu_saturation",
                        definition_version=1,
                        title="CPU Saturation",
                        summary="CPU saturated",
                        category="saturation",
                        severity="critical",
                        service="checkout-api",
                        input_metrics_json={},
                        facts_json={},
                        evidence_json=[],
                        matched_conditions_json=[],
                        confidence=0.9,
                        correlation_json={},
                        created_at=now - timedelta(hours=1),
                    ),
                ]
            )
            db.commit()

        res = client.get("/api/overview/summary", params={"window": "24h"})
        assert res.status_code == 200
        payload = res.json()
        assert payload["active_findings"] == 1
        assert payload["open_cases"] == 1
        assert payload["behavior_changes"] == 1
        assert payload["impacted_services"] == 1
        assert payload["memory_items"] == 1
        assert payload["category_breakdown"] == [
            {"category": "anomaly", "count": 1},
            {"category": "behavior_change", "count": 1},
        ]
        trend_total = {severity: sum(point[severity] for point in payload["severity_trend"]) for severity in ("critical", "high", "medium", "low")}
        assert trend_total == {"critical": 1, "high": 1, "medium": 0, "low": 0}


def test_overview_summary_returns_empty_result_without_fabricated_points() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        res = client.get("/api/overview/summary", params={"window": "24h"})
        assert res.status_code == 200
        payload = res.json()
        assert payload["active_findings"] == 0
        assert payload["open_cases"] == 0
        assert payload["behavior_changes"] == 0
        assert payload["impacted_services"] == 0
        assert payload["memory_items"] == 0
        assert payload["severity_trend"] == []
        assert payload["category_breakdown"] == []


def test_overview_summary_honors_time_window() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    now = datetime.utcnow()
    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            db.add(_finding(1, "checkout-api", "critical", "behavior_change", now - timedelta(days=2)))
            db.commit()

        res_24h = client.get("/api/overview/summary", params={"window": "24h"})
        res_7d = client.get("/api/overview/summary", params={"window": "7d"})
        assert res_24h.status_code == 200
        assert res_24h.json()["active_findings"] == 0
        assert res_24h.json()["severity_trend"] == []
        assert res_7d.status_code == 200
        assert res_7d.json()["active_findings"] == 1
        assert res_7d.json()["severity_trend"][0]["critical"] == 1


def test_overview_summary_supports_six_hour_window() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    now = datetime.utcnow()
    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            db.add(_finding(1, "checkout-api", "critical", "behavior_change", now - timedelta(hours=2)))
            db.add(_finding(2, "payments", "high", "behavior_change", now - timedelta(hours=10)))
            db.commit()

        res_6h = client.get("/api/overview/summary", params={"window": "6h"})
        assert res_6h.status_code == 200
        assert res_6h.json()["window"] == "6h"
        assert res_6h.json()["active_findings"] == 1
        assert client.get("/api/overview/summary", params={"window": "24h"}).json()["active_findings"] == 2


def test_overview_summary_rejects_invalid_window() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        res = client.get("/api/overview/summary", params={"window": "30d"})
        assert res.status_code == 422


def test_overview_summary_returns_service_error_when_database_unavailable() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")

    def broken_db():
        raise RuntimeError("database unavailable")
        yield

    app.dependency_overrides[get_db] = broken_db
    with TestClient(app, raise_server_exceptions=False) as client:
        res = client.get("/api/overview/summary", params={"window": "24h"})
        assert res.status_code == 500


def test_memory_stats_counts_case_memory_status_authoritatively() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    now = datetime.utcnow()
    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            db.add_all(
                [
                    _case(1, 1, "open", "pending", "indexed", now),
                    _case(2, 2, "open", "pending", "not_indexed", now),
                    _case(3, 3, "open", "pending", "stale", now),
                    _case(4, 4, "open", "pending", "error", now),
                ]
            )
            db.commit()

        res = client.get("/api/memory/stats")
        assert res.status_code == 200
        payload = res.json()
        assert payload["indexed_cases"] == 1
        assert payload["not_indexed_cases"] == 1
        assert payload["stale_cases"] == 1
        assert payload["error_cases"] == 1
        assert payload["total_cases"] == 4
        assert payload["source"] == "ops_operational_cases.memory_status"


class HealthyStore:
    def health(self) -> dict[str, str]:
        return {"status": "healthy"}


class UnhealthyStore:
    def health(self) -> dict[str, str]:
        return {"status": "unhealthy"}


class MalformedStore:
    def health(self) -> dict[str, object]:
        return {"unexpected": None}


class BrokenStore:
    def health(self) -> dict[str, str]:
        raise RuntimeError("qdrant unavailable")


def test_memory_stats_reports_healthy_store_with_indexed_cases() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    now = datetime.utcnow()
    memory_api._services["vector_store"] = HealthyStore()
    with TestClient(app) as client:
        memory_api._services["vector_store"] = HealthyStore()
        session_local = get_session_local()
        with session_local() as db:
            db.add(_case(1, 1, "open", "pending", "indexed", now))
            db.commit()

        res = client.get("/api/memory/stats")
        assert res.status_code == 200
        payload = res.json()
        assert payload["status"] == "healthy"
        assert payload["indexed_cases"] == 1


def test_memory_stats_reports_zero_indexed_cases_as_real_zero() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    now = datetime.utcnow()
    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            db.add(_case(1, 1, "open", "pending", "not_indexed", now))
            db.commit()

        res = client.get("/api/memory/stats")
        assert res.status_code == 200
        assert res.json()["indexed_cases"] == 0
        assert res.json()["total_cases"] == 1


def test_memory_stats_marks_unhealthy_or_malformed_store_without_losing_counts() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    now = datetime.utcnow()
    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            db.add(_case(1, 1, "open", "pending", "indexed", now))
            db.commit()

        memory_api._services["vector_store"] = UnhealthyStore()
        unhealthy = client.get("/api/memory/stats")
        assert unhealthy.status_code == 200
        assert unhealthy.json()["status"] == "unhealthy"
        assert unhealthy.json()["indexed_cases"] == 1

        memory_api._services["vector_store"] = MalformedStore()
        malformed = client.get("/api/memory/stats")
        assert malformed.status_code == 200
        assert malformed.json()["status"] == "unknown"
        assert malformed.json()["indexed_cases"] == 1


def test_memory_stats_returns_service_error_for_vector_store_failure() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app, raise_server_exceptions=False) as client:
        memory_api._services["vector_store"] = BrokenStore()
        res = client.get("/api/memory/stats")
        assert res.status_code == 500


def test_overview_counts_a_problem_seen_by_several_runs_once() -> None:
    # Scheduled runs re-analyze overlapping windows, so the same problem is saved once per run,
    # linked to the first by problem_id (intelligence/storage/postgres_store.py).
    app = create_app("sqlite+pysqlite:///:memory:")
    now = datetime.utcnow()
    with TestClient(app) as client:
        with get_session_local()() as db:
            first = _finding(1, "checkout-api", "critical", "behavior_change", now - timedelta(hours=2))
            repeats = [_finding(finding_id, "checkout-api", "critical", "behavior_change", now - timedelta(hours=1)) for finding_id in (2, 3)]
            for repeat in repeats:
                repeat.problem_id = 1
            other = _finding(4, "payments", "critical", "behavior_change", now - timedelta(hours=1))
            closed_first = _finding(5, "search", "critical", "behavior_change", now - timedelta(hours=3))
            closed_repeat = _finding(6, "search", "critical", "behavior_change", now - timedelta(hours=1))
            closed_repeat.problem_id = 5
            db.add_all([first, *repeats, other, closed_first, closed_repeat])
            db.add(_case(1, 5, "closed", "resolved", "indexed", now))
            db.commit()

        payload = client.get("/api/overview/summary", params={"window": "24h"}).json()

    assert payload["active_findings"] == 2
    assert payload["category_breakdown"] == [{"category": "behavior_change", "count": 3}]


def test_overview_splits_problems_into_needing_attention_and_context(monkeypatch) -> None:
    # A problem needs attention when any of its findings does (services/finding_trust.py).
    from backend.app.api import overview as overview_api

    tiers = {1: "context", 2: "needs_attention", 3: "context"}
    monkeypatch.setattr(overview_api, "finding_trust", lambda db, rows: {row.id: {"tier": tiers[row.id]} for row in rows})
    app = create_app("sqlite+pysqlite:///:memory:")
    now = datetime.utcnow()
    with TestClient(app) as client:
        with get_session_local()() as db:
            first = _finding(1, "checkout-api", "critical", "behavior_change", now - timedelta(hours=2))
            repeat = _finding(2, "checkout-api", "critical", "behavior_change", now - timedelta(hours=1))
            repeat.problem_id = 1
            other = _finding(3, "payments", "critical", "behavior_change", now - timedelta(hours=1))
            db.add_all([first, repeat, other])
            db.commit()

        payload = client.get("/api/overview/summary", params={"window": "24h"}).json()

    assert (payload["active_findings"], payload["attention_findings"], payload["context_findings"]) == (2, 1, 1)
