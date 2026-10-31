"""Reads kept for Admins (backend/app/roles.py _ADMIN_READS): set-up details and analyzer lab work.
Everyone else gets GET /api/setup/summary for the setup reminder and the plugin's header chips."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.app.roles import required_role


def _grafana(role: str) -> dict[str, str]:
    return {"X-Grafana-Context": json.dumps({"UserID": 3, "Login": "sam", "OrgRole": role, "IsAnonymous": False})}


@pytest.mark.parametrize(
    ("method", "path", "needed"),
    [
        ("GET", "/api/setup/check", "Admin"),
        ("HEAD", "/api/setup/check/", "Admin"),
        ("OPTIONS", "/api/setup/check", None),
        ("GET", "/api/setup/summary", None),
        ("GET", "/api/admin/analyzers", "Admin"),
        ("GET", "/api/analyzer-labs/drafts/4/adapter-source", "Admin"),
        ("GET", "/api/analyzer-labs/config-suggestions", "Admin"),
        ("GET", "/api/case-imports/profiles", "Admin"),
        ("GET", "/api/case-imports", "Admin"),
        ("GET", "/api/findings", None),
        ("GET", "/api/prometheus/connections", None),
        ("GET", "/api/assistant/feedback/flagged", None),
    ],
)
def test_each_read_needs_the_role_the_table_says(method: str, path: str, needed: str | None) -> None:
    assert required_role(method, path) == needed


@pytest.mark.parametrize("role", ["Viewer", "Editor"])
def test_set_up_details_are_refused_below_admin(client: TestClient, role: str) -> None:
    for path in ("/api/setup/check", "/api/admin/analyzers", "/api/case-imports/profiles", "/api/analyzer-labs/config-suggestions"):
        refused = client.get(path, headers=_grafana(role))
        assert refused.status_code == 403, path
        assert refused.json()["detail"] == "Only Grafana admins can see this."


def test_admins_and_requests_without_a_role_still_read_them(client: TestClient) -> None:
    assert client.get("/api/setup/check", headers=_grafana("Admin")).status_code == 200
    assert client.get("/api/setup/check").status_code == 200


def test_the_summary_has_every_check_but_none_of_its_details(client: TestClient) -> None:
    full = client.get("/api/setup/check").json()
    summary = client.get("/api/setup/summary", headers=_grafana("Viewer")).json()

    assert [(check["id"], check["group"], check["status"], check["title"]) for check in summary["checks"]] == [
        (check["id"], check["group"], check["status"], check["title"]) for check in full["checks"]
    ]
    for check in summary["checks"]:
        assert check["detail"] == ""
        assert (check["tried"], check["cause"], check["fix"], check["snippet"]) == (None, None, [], None)
    assert summary["you"] == {"name": "sam", "role": "Viewer", "via": "grafana"}
    assert summary["version"] == full["version"]


def test_the_web_ui_wording_names_the_ops_signals_admin(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.setenv("OPS_SIGNALS_DEV_USER", "priya@example.com:Editor")
    refused = client.get("/api/setup/check")
    assert refused.status_code == 403
    assert refused.json()["detail"] == "Only Ops Signals admins can see this."
    assert client.get("/api/setup/summary").status_code == 200


def test_a_token_without_sign_in_warns_that_everyone_can_change_everything(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.setenv("OPS_SIGNALS_API_TOKEN", "s3cret")
    monkeypatch.delenv("OPS_SIGNALS_AUTH_MODE", raising=False)
    checks = {check["id"]: check for check in client.get("/api/setup/check", headers={"Authorization": "Bearer s3cret"}).json()["checks"]}
    assert checks["login"]["status"] == "warn"
    assert "everyone who uses it can see and change everything" in checks["login"]["detail"]
    assert any("OPS_SIGNALS_AUTH_MODE=proxy-headers" in step for step in checks["login"]["fix"])


def test_through_grafana_with_a_token_the_login_steps_are_done(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.setenv("OPS_SIGNALS_API_TOKEN", "s3cret")
    monkeypatch.delenv("OPS_SIGNALS_AUTH_MODE", raising=False)
    headers = {"Authorization": "Bearer s3cret", **_grafana("Admin")}
    login = next(check for check in client.get("/api/setup/check", headers=headers).json()["checks"] if check["id"] == "login")
    assert (login["status"], login["step"]) == ("ok", 3)
    assert login["detail"] == "API locked. You are sam (Admin) through Grafana, so Grafana's roles apply."
    # The step is no detail: every role's summary carries it, for the plugin's strip.
    summary = client.get("/api/setup/summary", headers={"Authorization": "Bearer s3cret", **_grafana("Viewer")}).json()
    assert next(check["step"] for check in summary["checks"] if check["id"] == "login") == 3
