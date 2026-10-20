"""Web UI sign-in through the company's sign-in proxy (OPS_SIGNALS_AUTH_MODE=proxy-headers), and the
dev-only OPS_SIGNALS_DEV_USER (backend/app/identity.py, docs/web-ui-sign-in.md)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.config import AuthConfig
from backend.app.identity import Actor, proxy_actor
from tests.api_backend.test_cases import _create_finding

TOKEN = "s3cret"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PROXY_AUTH = AuthConfig(mode="proxy-headers", editor_groups=["sre", "oncall"], admin_groups=["platform-admins"])


def _signed_in(email: str, groups: str = "") -> dict[str, str]:
    return AUTH | {"X-Forwarded-Email": email, "X-Forwarded-Groups": groups}


@pytest.fixture()
def sign_in_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_SIGNALS_API_TOKEN", TOKEN)
    monkeypatch.setenv("OPS_SIGNALS_AUTH_MODE", "proxy-headers")
    monkeypatch.setenv("OPS_SIGNALS_AUTH_EDITOR_GROUPS", "sre,oncall")
    monkeypatch.setenv("OPS_SIGNALS_AUTH_ADMIN_GROUPS", "platform-admins")
    monkeypatch.delenv("OPS_SIGNALS_DEV_USER", raising=False)


def test_groups_decide_the_role_and_say_which_group_did() -> None:
    def actor(groups: str) -> Actor | None:
        return proxy_actor({"X-Forwarded-Email": "priya@example.com", "X-Forwarded-Groups": groups}, PROXY_AUTH, TOKEN)

    assert actor("payments, sre") == Actor(name="priya@example.com", role="Editor", via="proxy", groups=("payments", "sre"), granted_by="sre")
    assert actor("sre;platform-admins").role == "Admin"
    assert actor("platform-admins").granted_by == "platform-admins"
    assert (actor("payments").role, actor("").role) == ("Viewer", "Viewer")


def test_user_headers_count_only_with_sign_in_on_and_a_token() -> None:
    headers = {"X-Forwarded-Email": "priya@example.com", "X-Forwarded-Groups": "sre"}
    assert proxy_actor(headers, AuthConfig(), TOKEN) is None
    assert proxy_actor(headers, PROXY_AUTH, None) is None
    assert proxy_actor({}, PROXY_AUTH, TOKEN) is None
    custom = AuthConfig(mode="proxy-headers", user_header="X-Auth-Request-User", editor_groups=["sre"])
    assert proxy_actor({"X-Auth-Request-User": "sam"}, custom, TOKEN).name == "sam"


def test_the_dev_user_works_only_without_a_token() -> None:
    dev = AuthConfig(dev_user="priya@example.com:viewer")
    assert proxy_actor({}, dev, None) == Actor(name="priya@example.com", role="Viewer", via="dev")
    assert proxy_actor({}, AuthConfig(dev_user="sam:Owner"), None).role == "Viewer"
    assert proxy_actor({}, dev, TOKEN) is None


def test_a_signed_in_viewer_is_refused_with_the_web_ui_wording(sign_in_env, client: TestClient) -> None:
    finding_id = _create_finding()

    refused = client.post(f"/api/findings/{finding_id}/feedback", json={"verdict": "real_problem"}, headers=_signed_in("vic@example.com", "payments"))
    assert refused.status_code == 403
    assert refused.json()["detail"].endswith("Ask your Ops Signals admin for the Editor role.")

    allowed = client.post(f"/api/findings/{finding_id}/feedback", json={"verdict": "real_problem"}, headers=_signed_in("priya@example.com", "sre"))
    assert allowed.status_code == 200
    assert allowed.json()["trust"]["answered_by"] == "priya@example.com"


def test_me_says_who_and_why(sign_in_env, client: TestClient) -> None:
    me = client.get("/api/me", headers=_signed_in("priya@example.com", "payments,sre")).json()
    assert me == {
        "signed_in": True, "name": "priya@example.com", "role": "Editor", "via": "proxy",
        "groups": ["payments", "sre"], "granted_by": "sre", "mode": "proxy-headers", "problem": None,
    }

    anonymous = client.get("/api/me", headers=AUTH).json()
    assert (anonymous["signed_in"], anonymous["via"]) == (False, "none")
    assert "had no user header" in anonymous["problem"]


def test_a_grafana_user_still_wins_over_user_headers(sign_in_env, client: TestClient) -> None:
    grafana = {"X-Grafana-Context": json.dumps({"Login": "admin", "Email": "admin@localhost", "OrgRole": "Admin"})}
    me = client.get("/api/me", headers=_signed_in("vic@example.com", "payments") | grafana).json()
    assert (me["name"], me["role"], me["via"]) == ("admin", "Admin", "grafana")


def test_without_sign_in_nothing_changes(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.delenv("OPS_SIGNALS_AUTH_MODE", raising=False)
    monkeypatch.delenv("OPS_SIGNALS_DEV_USER", raising=False)
    me = client.get("/api/me").json()
    assert (me["signed_in"], me["mode"], me["problem"]) == (False, "none", None)
    assert client.post(f"/api/findings/{_create_finding()}/feedback", json={"verdict": "real_problem"}).status_code == 200


def test_the_setup_check_login_row_says_who_signed_in(sign_in_env, client: TestClient) -> None:
    checks = {check["id"]: check for check in client.get("/api/setup/check", headers=_signed_in("priya@example.com", "sre")).json()["checks"]}
    assert checks["login"]["status"] == "ok"
    assert checks["login"]["detail"] == "Company sign-in (proxy headers) is on · you are priya@example.com (Editor, group sre) through company sign-in."

    missing = {check["id"]: check for check in client.get("/api/setup/check", headers=AUTH).json()["checks"]}
    assert missing["login"]["status"] == "warn"
    assert "no X-Forwarded-Email header" in missing["login"]["detail"]


def test_the_dev_user_is_flagged_in_the_setup_check(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.setenv("OPS_SIGNALS_DEV_USER", "priya@example.com:Viewer")
    checks = {check["id"]: check for check in client.get("/api/setup/check").json()["checks"]}
    assert checks["login"]["status"] == "warn"
    assert "OPS_SIGNALS_DEV_USER" in checks["login"]["detail"]
    assert client.post(f"/api/findings/{_create_finding()}/feedback", json={"verdict": "real_problem"}).status_code == 403


def test_the_web_ui_nginx_drops_grafana_identity_headers() -> None:
    config = (Path(__file__).resolve().parents[2] / "docker" / "nginx.web.conf").read_text()
    assert 'proxy_set_header X-Grafana-Context "";' in config
    assert 'proxy_set_header X-Grafana-Id "";' in config
