"""A local OpenID Connect provider for trying Ops Signals' sign-in before a company provider is set up
(docs/web-ui-sign-in.md). OPS_SIGNALS_TEST_SIGN_IN=true in .env makes scripts/run_all.sh start it; the
Playwright sign-in spec and the backend tests use it too.

For this computer only: it listens on 127.0.0.1, its accounts have no passwords, it sends people back
only to a loopback address, and the backend accepts it only at a 127.0.0.1 issuer (backend/app/oidc.py).

    python -m backend.devtools.test_sign_in_provider [--port 9400]
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import secrets
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

CLIENT_ID = "ops-signals-test"
CLIENT_SECRET = "ops-signals-test-secret"
ADMIN_GROUP = "ops-signals-admins"
EDITOR_GROUP = "ops-signals-editors"
VIEWER_GROUP = "ops-signals-viewers"
DEFAULT_PORT = 9400
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_CODE_SECONDS = 60


@dataclass(frozen=True)
class TestAccount:
    __test__ = False
    email: str
    name: str
    # None: the ID token has no groups claim at all, to see what a provider that leaves them out does.
    group: str | None
    role: str


ACCOUNTS = (
    TestAccount("sam@example.com", "Sam", VIEWER_GROUP, "Viewer"),
    TestAccount("priya@example.com", "Priya", EDITOR_GROUP, "Editor"),
    TestAccount("ada@example.com", "Ada", ADMIN_GROUP, "Admin"),
    TestAccount("lee@example.com", "Lee", None, "Viewer"),
)


def env_lines(issuer: str) -> list[str]:
    """The backend settings that point Ops Signals at this provider."""
    return [
        "OPS_SIGNALS_AUTH_MODE=oidc",
        f"OPS_SIGNALS_OIDC_ISSUER_URL={issuer}",
        f"OPS_SIGNALS_OIDC_CLIENT_ID={CLIENT_ID}",
        f"OPS_SIGNALS_OIDC_CLIENT_SECRET={CLIENT_SECRET}",
        f"OPS_SIGNALS_AUTH_ADMIN_GROUPS={ADMIN_GROUP}",
        f"OPS_SIGNALS_AUTH_EDITOR_GROUPS={EDITOR_GROUP}",
        "OPS_SIGNALS_OIDC_PROVIDER_NAME=test accounts",
    ]


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class ProviderError(Exception):
    def __init__(self, status: int, error: str, description: str) -> None:
        super().__init__(description)
        self.status, self.error, self.description = status, error, description


class TestSignInProvider:
    """The provider's logic, without a web server: discovery, keys, the account page, codes and tokens."""

    __test__ = False

    def __init__(self, issuer: str = f"http://127.0.0.1:{DEFAULT_PORT}", redirect_hosts: set[str] | None = None) -> None:
        self.issuer = issuer.rstrip("/")
        # Where it may send people back: a loopback address, unless a test names another host.
        self.redirect_hosts = redirect_hosts or _LOOPBACK
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._kid = secrets.token_hex(8)
        self._codes: dict[str, dict] = {}

    def discovery(self) -> dict:
        return {
            "issuer": self.issuer,
            "authorization_endpoint": f"{self.issuer}/authorize",
            "token_endpoint": f"{self.issuer}/token",
            "jwks_uri": f"{self.issuer}/keys",
            "end_session_endpoint": f"{self.issuer}/logout",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
            "scopes_supported": ["openid", "email", "profile"],
            "ops_signals_test_provider": True,
        }

    def jwks(self) -> dict:
        key = jwt.algorithms.RSAAlgorithm.to_jwk(self._key.public_key(), as_dict=True)
        return {"keys": [key | {"kid": self._kid, "use": "sig", "alg": "RS256"}]}

    def check_authorize(self, params: dict[str, str]) -> None:
        if params.get("client_id") != CLIENT_ID:
            raise ProviderError(400, "unauthorized_client", f"Unknown client {params.get('client_id')!r}; Ops Signals should use {CLIENT_ID}.")
        if params.get("response_type") != "code":
            raise ProviderError(400, "unsupported_response_type", "Only response_type=code is supported.")
        if params.get("code_challenge_method") != "S256" or not params.get("code_challenge"):
            raise ProviderError(400, "invalid_request", "A PKCE code_challenge with S256 is required.")
        target = urlsplit(params.get("redirect_uri", ""))
        if target.hostname not in self.redirect_hosts or target.path != "/api/auth/callback":
            raise ProviderError(400, "invalid_request", f"redirect_uri must be a local …/api/auth/callback, not {params.get('redirect_uri')!r}.")

    def choose(self, params: dict[str, str], email: str) -> str:
        """The address to send the browser back to once the person picked an account."""
        self.check_authorize(params)
        account = next((item for item in ACCOUNTS if item.email == email), None)
        if account is None:
            raise ProviderError(400, "access_denied", f"No test account {email!r}.")
        code = secrets.token_urlsafe(24)
        self._codes[code] = {"account": account, "params": dict(params), "exp": time.time() + _CODE_SECONDS}
        query = urlencode({"code": code, "state": params.get("state", "")})
        return f"{params['redirect_uri']}?{query}"

    def token(self, form: dict[str, str], authorization: str | None) -> dict:
        client_id, client_secret = form.get("client_id"), form.get("client_secret")
        if authorization and authorization.lower().startswith("basic "):
            client_id, _, client_secret = base64.b64decode(authorization[6:]).decode().partition(":")
        if client_id != CLIENT_ID or client_secret != CLIENT_SECRET:
            raise ProviderError(401, "invalid_client", "Wrong client id or secret.")
        grant = self._codes.pop(form.get("code", ""), None)
        if grant is None or grant["exp"] < time.time() or form.get("grant_type") != "authorization_code":
            raise ProviderError(400, "invalid_grant", "The code is unknown, used already or expired.")
        params = grant["params"]
        if form.get("redirect_uri") != params["redirect_uri"]:
            raise ProviderError(400, "invalid_grant", "redirect_uri differs from the sign-in's.")
        if _b64(hashlib.sha256(form.get("code_verifier", "").encode()).digest()) != params["code_challenge"]:
            raise ProviderError(400, "invalid_grant", "The PKCE code_verifier doesn't match.")
        account: TestAccount = grant["account"]
        now = int(time.time())
        claims = {"iss": self.issuer, "aud": CLIENT_ID, "sub": account.email, "email": account.email, "name": account.name,
                  "iat": now, "exp": now + 3600, "nonce": params.get("nonce")}
        if account.group:
            claims["groups"] = [account.group]
        id_token = jwt.encode(claims, self._key, algorithm="RS256", headers={"kid": self._kid})
        return {"access_token": secrets.token_urlsafe(24), "token_type": "Bearer", "expires_in": 3600, "id_token": id_token}

    def sign_out_target(self, post_logout_redirect_uri: str | None) -> str | None:
        target = urlsplit(post_logout_redirect_uri or "")
        return post_logout_redirect_uri if target.scheme in {"http", "https"} and target.hostname in self.redirect_hosts else None

    def account_page(self, params: dict[str, str]) -> str:
        hidden = "".join(f'<input type="hidden" name="{html.escape(key)}" value="{html.escape(value)}">' for key, value in params.items())
        rows = "".join(
            f'<button name="account" value="{html.escape(account.email)}"><span>{html.escape(account.email)}</span>'
            f'<small>{html.escape(account.group or "no groups")} → {html.escape(account.role)}</small></button>'
            for account in ACCOUNTS
        )
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Test sign-in</title><style>
body{{margin:0;font:15px/1.5 -apple-system,"Segoe UI",system-ui,sans-serif;background:#f6f7fb;color:#111827;display:grid;place-items:center;min-height:100vh;padding:16px;box-sizing:border-box}}
main{{background:#fff;border:1px solid #e3e8f1;border-radius:12px;padding:24px;max-width:420px;width:100%;display:grid;gap:12px}}
.note{{background:#fff7ed;color:#7c2d12;border-radius:8px;padding:10px 12px}}
form{{display:grid;gap:8px}}button{{display:flex;justify-content:space-between;gap:12px;align-items:center;font:inherit;text-align:left;padding:10px 12px;border:1px solid #e3e8f1;border-radius:8px;background:#fff;cursor:pointer}}
button:hover,button:focus-visible{{border-color:#4f46e5;outline:none}}small{{color:#64748b}}
</style></head><body><main>
<div class="note"><b>Test sign-in</b><br>For trying Ops Signals on this computer only. Not a real login.</div>
<b>Sign in as</b><form method="post" action="/authorize">{hidden}{rows}</form>
</main></body></html>"""

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Answers discovery, keys and token requests as the web server would: for httpx.MockTransport in tests."""
        path = request.url.path
        if path == "/.well-known/openid-configuration":
            return httpx.Response(200, json=self.discovery())
        if path == "/keys":
            return httpx.Response(200, json=self.jwks())
        if path == "/token" and request.method == "POST":
            form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
            try:
                return httpx.Response(200, json=self.token(form, request.headers.get("Authorization")))
            except ProviderError as error:
                return httpx.Response(error.status, json={"error": error.error, "error_description": error.description})
        return httpx.Response(404, json={"error": "not_found"})


def create_app(provider: TestSignInProvider) -> FastAPI:
    app = FastAPI(title="Ops Signals test sign-in", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/.well-known/openid-configuration")
    def discovery() -> dict:
        return provider.discovery()

    @app.get("/keys")
    def keys() -> dict:
        return provider.jwks()

    @app.get("/authorize", response_class=HTMLResponse)
    def authorize(request: Request) -> HTMLResponse:
        params = dict(request.query_params)
        try:
            provider.check_authorize(params)
        except ProviderError as error:
            return HTMLResponse(f"<p>{html.escape(error.description)}</p>", status_code=error.status)
        return HTMLResponse(provider.account_page(params))

    @app.post("/authorize", response_model=None)
    async def chose(request: Request) -> RedirectResponse | HTMLResponse:
        form = {key: str(value) for key, value in (await request.form()).items()}
        email = form.pop("account", "")
        try:
            return RedirectResponse(provider.choose(form, email), status_code=303)
        except ProviderError as error:
            return HTMLResponse(f"<p>{html.escape(error.description)}</p>", status_code=error.status)

    @app.post("/token")
    async def token(request: Request) -> JSONResponse:
        form = {key: str(value) for key, value in (await request.form()).items()}
        try:
            return JSONResponse(provider.token(form, request.headers.get("Authorization")))
        except ProviderError as error:
            return JSONResponse({"error": error.error, "error_description": error.description}, status_code=error.status)

    @app.get("/logout", response_model=None)
    def logout(post_logout_redirect_uri: str | None = None) -> RedirectResponse | HTMLResponse:
        target = provider.sign_out_target(post_logout_redirect_uri)
        if target:
            return RedirectResponse(target, status_code=303)
        return HTMLResponse("<p>Signed out of the test provider.</p>")

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Local test sign-in provider for Ops Signals (this computer only).")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    issuer = f"http://127.0.0.1:{args.port}"
    print("Test sign-in provider for trying Ops Signals on this computer only.")
    print("Set these on the backend (with OPS_SIGNALS_API_TOKEN) and restart it:")
    for line in env_lines(issuer):
        print(f"  {line}")
    print("Accounts: " + " · ".join(f"{account.email.split('@')[0]} = {account.role}" for account in ACCOUNTS))

    import uvicorn

    uvicorn.run(create_app(TestSignInProvider(issuer)), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
