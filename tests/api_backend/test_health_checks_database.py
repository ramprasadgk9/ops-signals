"""QA-10: /api/health said "ok" with Postgres down, so Docker and the Helm readiness probe kept
routing to a backend that failed every real request."""

from __future__ import annotations

import time
from unittest.mock import patch

from backend.app.api import services


def _database_down() -> None:
    raise OSError("connection refused")


def test_health_reports_the_database_when_it_is_up(client) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_is_503_when_the_database_is_down(client) -> None:
    with patch.object(services, "_ping_database", _database_down):
        response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unavailable"}


def test_liveness_stays_ok_when_the_database_is_down(client) -> None:
    # Restarting the backend doesn't fix a database outage, so liveness ignores it.
    with patch.object(services, "_ping_database", _database_down):
        assert client.get("/api/health/live").json() == {"status": "ok"}
        assert client.get("/api/health/live").status_code == 200


def test_a_hanging_database_check_answers_within_the_timeout_and_does_not_pile_up(client) -> None:
    calls = 0

    def hang() -> None:
        nonlocal calls
        calls += 1
        time.sleep(1.5)

    with patch.object(services, "_ping_database", hang), patch.object(services, "DATABASE_CHECK_TIMEOUT_SECONDS", 0.2):
        started = time.perf_counter()
        first = client.get("/api/health")
        second = client.get("/api/health")
        elapsed = time.perf_counter() - started

    assert first.status_code == second.status_code == 503
    assert elapsed < 1.0
    # The second call waited on the check still running instead of starting another.
    assert calls == 1
    time.sleep(1.5)


def test_health_recovers_once_the_database_is_back(client) -> None:
    with patch.object(services, "_ping_database", _database_down):
        assert client.get("/api/health").status_code == 503

    assert client.get("/api/health").status_code == 200
