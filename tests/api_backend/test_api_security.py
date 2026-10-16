"""Access controls from docs/security-model.md: the optional API token, the receivers' token
fallback, the testing and file-write switches, configurable CORS, and input hardening on the
endpoints that write files."""

from __future__ import annotations

import ast
from collections.abc import Callable, Generator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from backend.app.api.admin_analyzers import AnalyzerConfigIn
from backend.app.api.analyzer_labs import _adapter_stub_text
from backend.app.main import create_app

TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
DRAFT_DEFINITION = {"id": "pair", "title": "Pair"}


@pytest.fixture()
def make_client(monkeypatch: pytest.MonkeyPatch) -> Callable[..., contextmanager]:
    """Builds the app after applying env overrides; the conftest default turns file writes on, so
    each test states the setting it's about."""

    @contextmanager
    def _make(**env: str | None) -> Generator[TestClient, None, None]:
        for name, value in env.items():
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
            yield client

    return _make


def test_without_token_the_api_stays_open(make_client) -> None:
    with make_client() as client:
        assert client.get("/api/findings").status_code == 200


def test_token_protects_every_route_except_health(make_client) -> None:
    with make_client(OPS_SIGNALS_API_TOKEN=TOKEN) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/health/live").status_code == 200
        assert client.get("/api/findings").status_code == 401
        assert client.get("/api/findings", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.get("/api/findings", headers=AUTH).status_code == 200
        # Reads on a receiver's path are not receivers: the API token applies.
        assert client.get("/api/events").status_code == 401


def test_receivers_fall_back_to_the_api_token(make_client) -> None:
    with make_client(OPS_SIGNALS_API_TOKEN=TOKEN) as client:
        assert client.post("/api/alerts", json={"alert_name": "HighLatency"}).status_code == 401
        assert client.post("/api/alerts", json={"alert_name": "HighLatency"}, headers=AUTH).status_code == 202
        event = {"service": "checkout-api", "type": "deploy"}
        assert client.post("/api/events", json=event).status_code == 401
        assert client.post("/api/events", json=event, headers=AUTH).status_code == 201


def test_receiver_token_takes_precedence(make_client) -> None:
    with make_client(OPS_SIGNALS_API_TOKEN=TOKEN, OPS_SIGNALS_ALERT_RECEIVER_TOKEN="receiver-token") as client:
        payload = {"alert_name": "HighLatency"}
        assert client.post("/api/alerts", json=payload, headers=AUTH).status_code == 401
        receiver_auth = {"Authorization": "Bearer receiver-token"}
        assert client.post("/api/alerts", json=payload, headers=receiver_auth).status_code == 202


def test_testing_api_is_off_by_default(make_client) -> None:
    body = {"confirm": "RESET_OPS_SIGNALS_TEST_DATA", "clear_vector_memory": False}
    with make_client() as client:
        assert client.post("/api/testing/reset-operational-data", json=body).status_code == 404
    with make_client(OPS_SIGNALS_ENABLE_TESTING_API="true") as client:
        response = client.post("/api/testing/reset-operational-data", json={**body, "confirm": "nope"})
        assert response.status_code == 400


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/api/admin/analyzers", None),
        ("DELETE", "/api/admin/analyzers/some_analyzer", None),
        ("POST", "/api/analyzer-labs/drafts/1/promote", None),
        ("POST", "/api/analyzer-labs/drafts/1/backend-support", None),
        ("DELETE", "/api/analyzer-labs/analyzers/some_analyzer", None),
        ("POST", "/api/behavior-definitions/suggestions/1/promote", {}),
        ("POST", "/api/behavior-definitions/save-to-pack", {"definition": DRAFT_DEFINITION}),
    ],
)
def test_file_writes_are_off_by_default(make_client, method: str, path: str, body: dict | None) -> None:
    with make_client(OPS_SIGNALS_ALLOW_FILE_WRITES=None) as client:
        response = client.request(method, path, json=body)
        assert response.status_code == 403
        assert "OPS_SIGNALS_ALLOW_FILE_WRITES" in response.json()["detail"]


@pytest.mark.parametrize("pack_file", ["../../evil.yml", "/etc/passwd.yml", "sub/dir.yml", "notes.txt"])
def test_pack_file_must_be_a_bare_yaml_name(make_client, pack_file: str) -> None:
    with make_client() as client:
        response = client.post(
            "/api/behavior-definitions/save-to-pack",
            json={"definition": DRAFT_DEFINITION, "pack_file": pack_file},
        )
        assert response.status_code == 422


def test_cors_origins_are_configurable(make_client) -> None:
    preflight = {"Access-Control-Request-Method": "GET"}
    with make_client(OPS_SIGNALS_CORS_ORIGINS="https://grafana.example.com") as client:
        allowed = client.options("/api/findings", headers={**preflight, "Origin": "https://grafana.example.com"})
        assert allowed.headers.get("access-control-allow-origin") == "https://grafana.example.com"
        denied = client.options("/api/findings", headers={**preflight, "Origin": "http://localhost:3000"})
        assert "access-control-allow-origin" not in denied.headers


def test_adapter_stub_keeps_user_text_out_of_the_code() -> None:
    hostile = 'X"""\nimport os\nos.system("id")\n"""'
    config = AnalyzerConfigIn(
        analyzer_id="motif_detection",
        display_name=hostile,
        template_type="Motif",
        library='math"\nimport os',
        supported_profiles=["motif"],
        scoring_rules=[{"metric": "seasonality_strength", "operator": "gte", "threshold": 0.4, "add": 0.2}],
        selected_explanation="",
        excluded_explanation="",
    )
    tree = ast.parse(_adapter_stub_text(config))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert "os" not in imported
    assert not any(isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) for node in tree.body)
    title = next(
        kw.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "title"
    )
    assert title == hostile
