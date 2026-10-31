"""The backend's own sign-in over OpenID Connect (OPS_SIGNALS_AUTH_MODE=oidc; backend/app/oidc.py,
backend/app/api/auth.py). The local test provider (backend/devtools/test_sign_in_provider.py) answers
through httpx.MockTransport, so nothing reaches the network."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from backend.app import oidc
from backend.app.config import get_auth_config
from backend.devtools.test_sign_in_provider import ADMIN_GROUP, CLIENT_ID, CLIENT_SECRET, EDITOR_GROUP, TestSignInProvider

TOKEN = "s3cret-api-token"
ISSUER = "https://idp.example.com"


class CompanyProvider(TestSignInProvider):
    """The test provider without its test marker: stands for a company's real provider."""

    def discovery(self) -> dict:
        document = super().discovery()
        document.pop("ops_signals_test_provider")
        return document


@pytest.fixture()
def provider(monkeypatch: pytest.MonkeyPatch) -> CompanyProvider:
    idp = CompanyProvider(ISSUER, redirect_hosts={"testserver"})
    monkeypatch.setattr(oidc, "http_transport", httpx.MockTransport(idp.handle))
    oidc.clear_cache()
    oidc.recent_groups_missing.clear()
    for name, value in {
        "OPS_SIGNALS_API_TOKEN": TOKEN,
        "OPS_SIGNALS_AUTH_MODE": "oidc",
        "OPS_SIGNALS_OIDC_ISSUER_URL": ISSUER,
        "OPS_SIGNALS_OIDC_CLIENT_ID": CLIENT_ID,
        "OPS_SIGNALS_OIDC_CLIENT_SECRET": CLIENT_SECRET,
        "OPS_SIGNALS_AUTH_ADMIN_GROUPS": ADMIN_GROUP,
        "OPS_SIGNALS_AUTH_EDITOR_GROUPS": EDITOR_GROUP,
    }.items():
        monkeypatch.setenv(name, value)
    for name in ("OPS_SIGNALS_DEV_USER", "OPS_SIGNALS_OIDC_ALLOWED_GROUPS", "OPS_SIGNALS_SESSION_SECRET", "OPS_SIGNALS_PUBLIC_URL"):
        monkeypatch.delenv(name, raising=False)
    yield idp
    oidc.clear_cache()


def _start(client: TestClient, next_path: str = "/findings") -> dict[str, str]:
    started = client.get("/api/auth/login", params={"next": next_path}, follow_redirects=False)
    assert started.status_code == 303, started.text
    assert started.headers["location"].startswith(f"{ISSUER}/authorize?")
    return {key: values[0] for key, values in parse_qs(urlsplit(started.headers["location"]).query).items()}


def sign_in(client: TestClient, provider: TestSignInProvider, email: str, next_path: str = "/findings") -> httpx.Response:
    back = provider.choose(_start(client, next_path), email)
    return client.get(back, follow_redirects=False)


def _error(response: httpx.Response) -> dict[str, str]:
    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    assert location.path == "/sign-in"
    return {key: values[0] for key, values in parse_qs(location.query).items()}


def test_signing_in_sets_a_session_with_the_role_from_the_groups(provider, client: TestClient) -> None:
    for email, role, group in (("ada@example.com", "Admin", ADMIN_GROUP), ("priya@example.com", "Editor", EDITOR_GROUP), ("sam@example.com", "Viewer", None)):
        client.cookies.clear()
        back = sign_in(client, provider, email)
        assert (back.status_code, back.headers["location"]) == (303, "/findings")
        me = client.get("/api/me").json()
        assert (me["signed_in"], me["name"], me["role"], me["via"], me["granted_by"]) == (True, email, role, "oidc", group)
        assert me["session_ends_at"] and me["login_url"] == "/api/auth/login"


def test_the_sign_in_request_uses_pkce_state_and_nonce(provider, client: TestClient) -> None:
    params = _start(client)
    assert params["code_challenge_method"] == "S256" and params["code_challenge"]
    assert params["state"] and params["nonce"]
    assert params["redirect_uri"] == "http://testserver/api/auth/callback"
    assert oidc.FLOW_COOKIE in client.cookies


def test_without_a_session_the_api_needs_the_token(provider, client: TestClient) -> None:
    assert client.get("/api/findings").status_code == 401
    assert client.get("/api/findings", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200
    me = client.get("/api/me").json()
    assert (me["signed_in"], me["mode"], me["login_url"], me["provider_name"]) == (False, "oidc", "/api/auth/login", "your company account")


def test_a_session_opens_the_api_and_signing_out_closes_it(provider, client: TestClient) -> None:
    sign_in(client, provider, "priya@example.com")
    assert client.get("/api/findings").status_code == 200

    out = client.post("/api/auth/logout", headers={"Origin": "http://testserver"})
    assert out.status_code == 200
    assert out.json()["redirect"].startswith(f"{ISSUER}/logout?")
    assert "post_logout_redirect_uri=http%3A%2F%2Ftestserver%2Fsigned-out" in out.json()["redirect"]
    assert client.get("/api/findings").status_code == 401


def test_signing_out_hands_the_provider_the_id_token_so_it_does_not_ask(provider, client: TestClient) -> None:
    sign_in(client, provider, "priya@example.com")
    hint = client.cookies.get(oidc.SIGN_OUT_HINT_COOKIE)
    assert hint and hint.count(".") == 2
    # Sent only to the sign-out endpoint, never readable by the page.
    cookie = next(c for c in client.cookies.jar if c.name == oidc.SIGN_OUT_HINT_COOKIE)
    assert cookie.path == oidc.LOGOUT_PATH and cookie.has_nonstandard_attr("HttpOnly")

    out = client.post("/api/auth/logout", headers={"Origin": "http://testserver"})
    query = parse_qs(urlsplit(out.json()["redirect"]).query)
    assert query["id_token_hint"] == [hint]
    assert oidc.SIGN_OUT_HINT_COOKIE not in client.cookies


def test_without_the_hint_sign_out_still_works(provider, client: TestClient) -> None:
    sign_in(client, provider, "priya@example.com")
    client.cookies.delete(oidc.SIGN_OUT_HINT_COOKIE, path=oidc.LOGOUT_PATH)
    out = client.post("/api/auth/logout", headers={"Origin": "http://testserver"})
    assert "id_token_hint" not in out.json()["redirect"]
    assert out.json()["redirect"].startswith(f"{ISSUER}/logout?")


def test_an_id_token_too_big_for_a_cookie_is_left_out(provider, monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.setattr(oidc, "MAX_SIGN_OUT_HINT", 10)
    sign_in(client, provider, "priya@example.com")
    assert oidc.SIGN_OUT_HINT_COOKIE not in client.cookies
    assert client.get("/api/findings").status_code == 200


def test_a_viewer_can_sign_out(provider, client: TestClient) -> None:
    sign_in(client, provider, "sam@example.com")
    assert client.post("/api/auth/logout", headers={"Origin": "http://testserver"}).status_code == 200


def test_groups_left_out_say_so_once_and_sign_in_as_viewer(provider, client: TestClient) -> None:
    back = sign_in(client, provider, "lee@example.com", "/cases")
    assert _error(back) == {"error": "groups", "next": "/cases"}
    me = client.get("/api/me").json()
    assert (me["signed_in"], me["role"]) == (True, "Viewer")


def test_allowed_groups_keep_others_out(provider, monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.setenv("OPS_SIGNALS_OIDC_ALLOWED_GROUPS", f"{ADMIN_GROUP},{EDITOR_GROUP}")
    refused = _error(sign_in(client, provider, "sam@example.com"))
    assert (refused["error"], refused["as"]) == ("not_allowed", "sam@example.com")
    assert refused["id"]
    assert client.get("/api/me").json()["signed_in"] is False
    assert client.get(sign_in(client, provider, "priya@example.com").headers["location"]).status_code in (200, 404)
    assert client.get("/api/me").json()["role"] == "Editor"


def test_a_sign_in_must_finish_in_the_same_browser(provider, client: TestClient) -> None:
    back = provider.choose(_start(client), "ada@example.com")
    client.cookies.clear()
    assert _error(client.get(back, follow_redirects=False))["error"] == "expired"


def test_a_changed_state_is_refused(provider, client: TestClient) -> None:
    params = _start(client)
    back = provider.choose(params | {"state": "someone-elses"}, "ada@example.com")
    assert _error(client.get(back, follow_redirects=False))["error"] == "expired"


def test_the_providers_own_refusal_is_shown(provider, client: TestClient) -> None:
    _start(client)
    refused = client.get("/api/auth/callback", params={"error": "access_denied", "error_description": "The user is not assigned to a role for the application."}, follow_redirects=False)
    error = _error(refused)
    assert (error["error"], error["said"]) == ("provider", "The user is not assigned to a role for the application.")


def test_next_stays_on_this_site(provider, client: TestClient) -> None:
    for unsafe in ("//evil.example/x", "https://evil.example", "/\\evil.example"):
        client.cookies.clear()
        assert sign_in(client, provider, "ada@example.com", unsafe).headers["location"] == "/"


@pytest.mark.parametrize("change", ["tamper", "expire"])
def test_a_changed_or_expired_session_is_refused(provider, client: TestClient, change: str) -> None:
    sign_in(client, provider, "ada@example.com")
    value = client.cookies[oidc.SESSION_COOKIE]
    if change == "tamper":
        body, _, mac = value.partition(".")
        payload = json.loads(oidc._unb64(body))
        payload["u"] = "mallory@example.com"
        forged = f"{oidc._b64(json.dumps(payload).encode())}.{mac}"
    else:
        secret = oidc.session_secret(get_auth_config(), TOKEN)
        forged = oidc.sign({"t": "session", "u": "ada@example.com", "g": [ADMIN_GROUP], "exp": int(time.time()) - 1}, secret)
    client.cookies.clear()
    client.cookies.set(oidc.SESSION_COOKIE, forged)
    assert client.get("/api/findings").status_code == 401
    assert client.get("/api/me").json()["signed_in"] is False


def test_a_flow_cookie_is_not_a_session(provider, client: TestClient) -> None:
    _start(client)
    flow = client.cookies[oidc.FLOW_COOKIE]
    client.cookies.set(oidc.SESSION_COOKIE, flow)
    assert client.get("/api/findings").status_code == 401


def test_a_change_from_another_site_is_refused(provider, client: TestClient) -> None:
    sign_in(client, provider, "priya@example.com")
    foreign = client.post("/api/findings/0/feedback", json={"verdict": "real_problem"}, headers={"Origin": "https://evil.example"})
    assert foreign.status_code == 403
    assert "didn't come from an Ops Signals page" in foreign.json()["detail"]
    assert client.post("/api/findings/0/feedback", json={"verdict": "real_problem"}).status_code == 403
    own = client.post("/api/findings/0/feedback", json={"verdict": "real_problem"}, headers={"Origin": "http://testserver"})
    assert own.status_code == 404


def test_public_url_is_this_sites_address(provider, monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.setenv("OPS_SIGNALS_PUBLIC_URL", "http://localhost:5174")
    provider.redirect_hosts = {"localhost"}
    assert _start(client)["redirect_uri"] == "http://localhost:5174/api/auth/callback"


def test_a_cookie_session_cannot_claim_to_be_a_grafana_user(provider, client: TestClient) -> None:
    sign_in(client, provider, "sam@example.com")
    grafana_admin = {"X-Grafana-Context": json.dumps({"Login": "admin", "OrgRole": "Admin"})}
    me = client.get("/api/me", headers=grafana_admin).json()
    assert (me["name"], me["role"], me["via"]) == ("sam@example.com", "Viewer", "oidc")
    # Grafana's plugin proxy adds the token, so there the header still counts.
    through_grafana = client.get("/api/me", headers=grafana_admin | {"Authorization": f"Bearer {TOKEN}"}).json()
    assert (through_grafana["role"], through_grafana["via"]) == ("Admin", "grafana")


def test_sign_in_proxy_headers_count_for_nothing(provider, client: TestClient) -> None:
    me = client.get("/api/me", headers={"Authorization": f"Bearer {TOKEN}", "X-Forwarded-Email": "eve@example.com", "X-Forwarded-Groups": ADMIN_GROUP}).json()
    assert (me["signed_in"], me["via"]) == (False, "none")


def test_sign_in_needs_the_api_token(provider, monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.delenv("OPS_SIGNALS_API_TOKEN")
    me = client.get("/api/me").json()
    assert "OPS_SIGNALS_API_TOKEN" in me["problem"]
    assert me["login_url"] is None
    assert _error(client.get("/api/auth/login", follow_redirects=False))["error"] == "config"


def test_the_client_secret_never_shows(provider, client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    sign_in(client, provider, "ada@example.com")
    sign_in(client, provider, "sam@example.com", "//evil")
    texts = [client.get("/api/me").text, client.get("/api/setup/check").text, client.get("/api/auth/test").text, caplog.text]
    assert all(CLIENT_SECRET not in text for text in texts)


def test_the_setup_check_login_row(provider, client: TestClient) -> None:
    sign_in(client, provider, "ada@example.com")
    login = next(check for check in client.get("/api/setup/check").json()["checks"] if check["id"] == "login")
    assert (login["status"], login["action"], login["step"]) == ("ok", "sign_in", 3)
    assert login["detail"].startswith("Company sign-in is on · you are ada@example.com (Admin, group ops-signals-admins) · groups that arrived: ops-signals-admins")


def test_me_shows_the_groups_that_arrived_even_when_none_match(provider, monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    """Lists that don't match what the provider sends (IDs, paths) make the person setting up a Viewer."""
    monkeypatch.setenv("OPS_SIGNALS_AUTH_ADMIN_GROUPS", f"{ADMIN_GROUP},11111111-aaaa")
    sign_in(client, provider, "ada@example.com")
    monkeypatch.setenv("OPS_SIGNALS_AUTH_ADMIN_GROUPS", "11111111-aaaa")
    monkeypatch.setenv("OPS_SIGNALS_AUTH_EDITOR_GROUPS", "")
    me = client.get("/api/me").json()
    # A Viewer now, so no Setup check: the chip's groups are how to find the right value.
    assert (me["role"], me["arrived_groups"]) == ("Viewer", [ADMIN_GROUP])


def test_the_setup_check_says_when_the_provider_cant_be_reached(provider, monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.setattr(oidc, "http_transport", httpx.MockTransport(lambda request: httpx.Response(503)))
    oidc.clear_cache()
    login = next(check for check in client.get("/api/setup/check", headers={"Authorization": f"Bearer {TOKEN}"}).json()["checks"] if check["id"] == "login")
    assert (login["status"], login["step"], login["detail"]) == ("fail", 2, "Company sign-in is on, but Ops Signals can't reach your provider.")
    assert "openid-configuration" in login["tried"]


def test_the_setup_check_warns_when_groups_never_arrive(provider, client: TestClient) -> None:
    for _ in range(5):
        client.cookies.clear()
        sign_in(client, provider, "lee@example.com")
    client.cookies.clear()
    login = next(check for check in client.get("/api/setup/check", headers={"Authorization": f"Bearer {TOKEN}"}).json()["checks"] if check["id"] == "login")
    assert (login["status"], login["detail"]) == ("warn", "Sign-ins work, but the last 5 had no groups, so everyone is a Viewer.")


def test_test_sign_in_is_for_admins(provider, client: TestClient) -> None:
    sign_in(client, provider, "sam@example.com")
    assert client.get("/api/auth/test").status_code == 403
    client.cookies.clear()
    sign_in(client, provider, "ada@example.com")
    tested = client.get("/api/auth/test").json()
    assert (tested["reachable"], tested["redirect_uri"], tested["test_provider"]) == (True, "http://testserver/api/auth/callback", False)


class TestTheIdTokenCheck:
    """verify_id_token on tokens made by hand, signed with the provider's own key unless a test says otherwise."""

    @pytest.fixture()
    def document(self, provider) -> dict:
        return oidc.discovery(ISSUER)

    @staticmethod
    def _token(provider, **changes) -> str:
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": CLIENT_ID, "sub": "ada", "email": "ada@example.com", "iat": now, "exp": now + 300, "nonce": "n-1"}
        headers = {"kid": provider._kid}
        claims |= {key: value for key, value in changes.items() if key not in {"kid"}}
        if "kid" in changes:
            headers["kid"] = changes["kid"]
        return jwt.encode({key: value for key, value in claims.items() if value is not None}, provider._key, algorithm="RS256", headers=headers)

    def test_a_good_token_passes(self, provider, document) -> None:
        assert oidc.verify_id_token(get_auth_config(), document, self._token(provider), "n-1")["email"] == "ada@example.com"

    @pytest.mark.parametrize(
        ("changes", "code"),
        [
            ({"nonce": "n-2"}, "expired"),
            ({"aud": "another-app"}, "provider"),
            ({"iss": "https://elsewhere.example"}, "provider"),
            ({"exp": int(time.time()) - 600}, "provider"),
            ({"kid": "not-a-key"}, "provider"),
        ],
    )
    def test_a_wrong_token_is_refused(self, provider, document, changes: dict, code: str) -> None:
        with pytest.raises(oidc.SignInError) as refused:
            oidc.verify_id_token(get_auth_config(), document, self._token(provider, **changes), "n-1")
        assert refused.value.code == code

    def test_unsigned_and_shared_secret_tokens_are_refused(self, provider, document) -> None:
        claims = {"iss": ISSUER, "aud": CLIENT_ID, "sub": "ada", "iat": int(time.time()), "exp": int(time.time()) + 300, "nonce": "n-1"}
        for token in (jwt.encode(claims, None, algorithm="none"), jwt.encode(claims, CLIENT_SECRET * 2, algorithm="HS256")):
            with pytest.raises(oidc.SignInError, match="isn't allowed"):
                oidc.verify_id_token(get_auth_config(), document, token, "n-1")


def test_the_test_provider_works_only_at_a_local_address(monkeypatch: pytest.MonkeyPatch) -> None:
    idp = TestSignInProvider("https://idp.example.com")
    monkeypatch.setattr(oidc, "http_transport", httpx.MockTransport(idp.handle))
    oidc.clear_cache()
    with pytest.raises(oidc.SignInError, match="127.0.0.1"):
        oidc.discovery("https://idp.example.com")
    oidc.clear_cache()


def test_the_test_provider_sends_people_back_only_to_a_local_address() -> None:
    idp = TestSignInProvider()
    good = {"client_id": CLIENT_ID, "response_type": "code", "code_challenge": "x", "code_challenge_method": "S256",
            "redirect_uri": "http://localhost:5174/api/auth/callback", "state": "s"}
    assert idp.choose(good, "sam@example.com").startswith("http://localhost:5174/api/auth/callback?code=")
    with pytest.raises(Exception, match="redirect_uri"):
        idp.choose(good | {"redirect_uri": "https://evil.example/api/auth/callback"}, "sam@example.com")
    assert idp.sign_out_target("https://evil.example/signed-out") is None


def test_the_test_providers_pages_work_over_http() -> None:
    """The routes run_all.sh and the Playwright spec use: the account page, picking an account, the token."""
    from backend.devtools.test_sign_in_provider import create_app

    idp = TestSignInProvider()
    web = TestClient(create_app(idp))
    request = {"client_id": CLIENT_ID, "response_type": "code", "code_challenge": oidc._b64(hashlib.sha256(b"v" * 43).digest()),
               "code_challenge_method": "S256", "redirect_uri": "http://localhost:5174/api/auth/callback", "state": "s", "nonce": "n"}
    page = web.get("/authorize", params=request)
    assert page.status_code == 200 and "sam@example.com" in page.text and "Not a real login" in page.text
    chose = web.post("/authorize", data=request | {"account": "priya@example.com"}, follow_redirects=False)
    assert chose.status_code == 303
    code = parse_qs(urlsplit(chose.headers["location"]).query)["code"][0]
    token = web.post("/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": request["redirect_uri"], "code_verifier": "v" * 43},
                     auth=(CLIENT_ID, CLIENT_SECRET))
    claims = jwt.decode(token.json()["id_token"], options={"verify_signature": False})
    assert (claims["email"], claims["groups"], claims["nonce"]) == ("priya@example.com", [EDITOR_GROUP], "n")
    assert web.get("/logout", params={"post_logout_redirect_uri": "http://localhost:5174/signed-out"}, follow_redirects=False).headers["location"] == "http://localhost:5174/signed-out"
