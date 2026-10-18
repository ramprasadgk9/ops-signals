"""QA-34 / QA-38: a dependency outage is a 503 that names it, and nothing answers with Starlette's
plain-text "Internal Server Error"."""

from __future__ import annotations

import sqlite3

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from qdrant_client.http.exceptions import ResponseHandlingException
from sqlalchemy.exc import OperationalError

from backend.app.api import memory as memory_module
from backend.app.api.errors import (
    DATABASE_UNAVAILABLE,
    MEMORY_UNAVAILABLE,
    internal_error,
    is_database_unavailable,
    memory_error,
)
from backend.app.main import create_app
from backend.app.models.db import get_db


def _postgres_down() -> OperationalError:
    return OperationalError("SELECT 1", {}, psycopg.OperationalError("connection to server at 10.0.0.12 port 5432 failed: Connection refused"))


def _qdrant_down() -> ResponseHandlingException:
    try:
        raise httpx.ConnectError("[Errno 61] Connection refused")
    except httpx.ConnectError as exc:
        return ResponseHandlingException(exc)


class _BrokenSession:
    def __init__(self, error: Exception):
        self.error = error

    def execute(self, *args, **kwargs):
        raise self.error

    def __getattr__(self, name):
        raise self.error


@pytest.fixture()
def client():
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _break_database(client, error: Exception) -> None:
    def broken():
        yield _BrokenSession(error)

    client.app.dependency_overrides[get_db] = broken


# --- classification --------------------------------------------------------------------------------


def test_a_refused_postgres_connection_is_an_outage_but_a_sqlite_sql_error_is_not() -> None:
    assert is_database_unavailable(_postgres_down())
    assert not is_database_unavailable(OperationalError("SELECT * FROM missing", {}, sqlite3.OperationalError("no such table: missing")))


def test_internal_error_says_the_database_is_down_without_its_address() -> None:
    error = internal_error("Analysis failed", _postgres_down())

    assert error.status_code == 503
    assert error.detail.startswith(DATABASE_UNAVAILABLE)
    assert "10.0.0.12" not in error.detail


def test_memory_error_names_qdrant_only_for_a_connection_failure() -> None:
    assert memory_error("Search failed", _qdrant_down()).status_code == 503
    assert memory_error("Search failed", RuntimeError("bug")).status_code == 500


def test_a_connection_failure_outside_memory_endpoints_is_not_blamed_on_qdrant() -> None:
    # Prometheus or Slack being unreachable is not a memory outage.
    error = internal_error("Analysis failed", httpx.ConnectError("refused"))

    assert error.status_code == 500
    assert MEMORY_UNAVAILABLE not in error.detail


# --- unhandled errors (QA-38) ----------------------------------------------------------------------


def test_a_route_without_its_own_handler_answers_json_with_an_error_id(client) -> None:
    _break_database(client, RuntimeError("secret internals"))

    response = client.get("/api/findings")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    detail = response.json()["detail"]
    assert "Details are in the server log (error " in detail
    assert "secret internals" not in detail


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/findings", None),
        ("post", "/api/events", {"type": "deploy", "service": "checkout"}),
    ],
)
def test_a_database_outage_on_a_route_without_its_own_handler_is_a_503(client, method, path, body) -> None:
    _break_database(client, _postgres_down())

    response = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)

    assert response.status_code == 503
    assert response.json()["detail"].startswith(DATABASE_UNAVAILABLE)
    assert "10.0.0.12" not in response.text


# --- operational memory (QA-34) --------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/cases/1/similar", "/api/mcp/cases/1/similar"])
def test_similar_cases_say_memory_is_unavailable_when_qdrant_is_down(client, monkeypatch, path) -> None:
    def down(**_kwargs):
        raise _qdrant_down()

    monkeypatch.setattr(memory_module._services["similarity_service"], "find_similar_cases", down)

    response = client.get(path)

    assert response.status_code == 503
    assert response.json()["detail"].startswith(MEMORY_UNAVAILABLE)


@pytest.mark.parametrize("path", ["/api/memory/chat", "/api/mcp/memory/chat"])
def test_memory_chat_says_memory_is_unavailable_when_qdrant_is_down(client, monkeypatch, path) -> None:
    def down(**_kwargs):
        raise _qdrant_down()

    monkeypatch.setattr(memory_module._services["similarity_service"].vector_store, "search", down)

    response = client.post(path, json={"message": "checkout latency"})

    assert response.status_code == 503
    assert response.json()["detail"].startswith(MEMORY_UNAVAILABLE)


def test_a_bug_in_memory_search_is_still_a_500(client, monkeypatch) -> None:
    def broken(**_kwargs):
        raise RuntimeError("bug")

    monkeypatch.setattr(memory_module._services["similarity_service"], "find_similar_cases", broken)

    response = client.get("/api/cases/1/similar")

    assert response.status_code == 500
    assert response.json()["detail"].startswith("Search failed.")


def test_memory_health_says_why_it_is_unhealthy(client, monkeypatch) -> None:
    store = memory_module._services["vector_store"]
    monkeypatch.setattr(store, "health", lambda: {"status": "unhealthy", "error": "connect to http://10.0.0.9:6333 refused"})

    payload = client.get("/api/memory/health").json()

    assert payload["status"] == "unhealthy"
    assert payload["detail"] == "Qdrant can't be reached."
    assert "10.0.0.9" not in str(payload)


def test_memory_that_never_came_up_says_why_in_plain_words(client, monkeypatch) -> None:
    from backend.app.memory import availability

    monkeypatch.setitem(memory_module._services, "similarity_service", None)
    monkeypatch.setattr(availability, "_state", {"status": availability.UNAVAILABLE})

    response = client.get("/api/cases/1/similar")

    assert response.status_code == 503
    assert response.json()["detail"] == "Operational memory can't reach its vector store right now; Ops Signals keeps retrying."
