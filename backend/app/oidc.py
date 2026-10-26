"""Built-in sign-in for the web UI over OpenID Connect (OPS_SIGNALS_AUTH_MODE=oidc; docs/web-ui-sign-in.md).

The browser goes to the company's identity provider and comes back with a code. The backend swaps the
code for an ID token, checks the token's signature and claims itself, and keeps who signed in in a
signed session cookie: nothing is stored server-side, so several backend replicas work the same.

The role is worked out on every request from the groups in the cookie and the current
OPS_SIGNALS_AUTH_ADMIN_GROUPS / _EDITOR_GROUPS lists (backend/app/identity.py), so changing a list applies
at once; a change of group membership applies at the next sign-in.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

import httpx
import jwt

from backend.app.config import AuthConfig

logger = logging.getLogger(__name__)

SESSION_COOKIE = "ops_signals_session"
FLOW_COOKIE = "ops_signals_sign_in"
FLOW_SECONDS = 600
CALLBACK_PATH = "/api/auth/callback"
LOGIN_PATH = "/api/auth/login"
_CACHE_SECONDS = 3600
_TIMEOUT_SECONDS = 5.0
_LEEWAY_SECONDS = 60
_MAX_NAME = 128
# Asymmetric signatures only: "none" and HMAC (which a client secret could forge) are refused.
_ALGORITHMS = {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"}
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}

# Tests swap in an httpx.MockTransport; nothing else sets it.
http_transport: httpx.BaseTransport | None = None

_lock = threading.Lock()
_documents: dict[str, tuple[float, dict]] = {}
# Whether the last few sign-ins came without groups, for Setup check's "everyone is a Viewer" warning.
recent_groups_missing: deque[bool] = deque(maxlen=5)


class SignInError(Exception):
    """A sign-in that can't finish. code picks what the web UI shows: not_allowed, expired, provider or
    config. detail goes to the log only, under error_id; shown is safe to put on the page."""

    def __init__(self, code: str, detail: str, shown: str | None = None) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.shown = shown
        self.error_id = secrets.token_hex(4)


@dataclass(frozen=True)
class Started:
    url: str
    flow_cookie: str


@dataclass(frozen=True)
class SignedIn:
    user: str
    display_name: str | None
    groups: tuple[str, ...]
    groups_missing: bool
    next_path: str


@dataclass(frozen=True)
class Session:
    user: str
    display_name: str | None
    groups: tuple[str, ...]
    groups_missing: bool
    expires_at: int


def is_loopback(url: str) -> bool:
    return (urlsplit(url).hostname or "") in _LOOPBACK


def setup_problem(auth: AuthConfig, api_token: str | None) -> str | None:
    """Why sign-in can't turn on yet, in words for an admin; None when the settings are complete."""
    missing = [name for name, value in (
        ("OPS_SIGNALS_OIDC_ISSUER_URL", auth.oidc_issuer_url),
        ("OPS_SIGNALS_OIDC_CLIENT_ID", auth.oidc_client_id),
        ("OPS_SIGNALS_OIDC_CLIENT_SECRET", auth.oidc_client_secret),
    ) if not value]
    if missing:
        return f"Company sign-in is on, but {', '.join(missing)} {'is' if len(missing) == 1 else 'are'} not set."
    if not api_token:
        return "Company sign-in needs OPS_SIGNALS_API_TOKEN too, so scripts and receivers stay protected. Set it and restart."
    issuer = auth.oidc_issuer_url or ""
    if urlsplit(issuer).scheme != "https" and not is_loopback(issuer):
        return f"OPS_SIGNALS_OIDC_ISSUER_URL must start with https:// (got {issuer})."
    return None


def session_secret(auth: AuthConfig, api_token: str | None) -> bytes | None:
    """OPS_SIGNALS_SESSION_SECRET, or one derived from the API token: rotating either signs everyone out."""
    if auth.session_secret:
        return auth.session_secret.encode()
    if api_token:
        return hmac.new(api_token.encode(), b"ops-signals-session-v1", hashlib.sha256).digest()
    return None


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(payload: dict, secret: bytes) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    return f"{body}.{_b64(hmac.new(secret, body.encode(), hashlib.sha256).digest())}"


def unsign(value: str | None, secret: bytes, kind: str) -> dict | None:
    """The payload of a cookie this backend signed for `kind` (session or flow), or None."""
    body, _, mac = (value or "").partition(".")
    if not body or not mac:
        return None
    if not hmac.compare_digest(mac, _b64(hmac.new(secret, body.encode(), hashlib.sha256).digest())):
        return None
    try:
        payload = json.loads(_unb64(body))
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get("t") != kind or not isinstance(payload.get("exp"), int):
        return None
    return payload if payload["exp"] > time.time() else None


def safe_next(path: str | None) -> str:
    """Only a path on this site: //evil.example and https://evil.example become /."""
    if not path or not path.startswith("/") or path.startswith("//") or path.startswith("/\\") or any(c in path for c in "\r\n"):
        return "/"
    return path[:512]


def _client() -> httpx.Client:
    return httpx.Client(timeout=_TIMEOUT_SECONDS, transport=http_transport, follow_redirects=False)


def _fetch_json(url: str, fresh: bool) -> dict:
    with _lock:
        cached = _documents.get(url)
    if cached and not fresh and time.time() - cached[0] < _CACHE_SECONDS:
        return cached[1]
    try:
        with _client() as client:
            response = client.get(url)
        response.raise_for_status()
        document = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise SignInError("provider", f"Couldn't read {url}: {error}") from error
    if not isinstance(document, dict):
        raise SignInError("provider", f"{url} didn't answer with a JSON object.")
    with _lock:
        _documents[url] = (time.time(), document)
    return document


def discovery(issuer: str, fresh: bool = False) -> dict:
    """The provider's discovery document, cached for an hour."""
    url = f"{issuer}/.well-known/openid-configuration"
    document = _fetch_json(url, fresh)
    if str(document.get("issuer", "")).rstrip("/") != issuer:
        raise SignInError("provider", f"{url} names the issuer {document.get('issuer')!r}, not {issuer!r}.")
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not document.get(key):
            raise SignInError("provider", f"{url} has no {key}.")
    if document.get("ops_signals_test_provider") and not is_loopback(issuer):
        raise SignInError("provider", "The local test provider only works at a 127.0.0.1 address.")
    return document


def is_test_provider(issuer: str) -> bool:
    """The local test provider (backend/devtools/test_sign_in_provider.py), which says so in its discovery."""
    try:
        return bool(discovery(issuer).get("ops_signals_test_provider"))
    except SignInError:
        return False


def clear_cache() -> None:
    with _lock:
        _documents.clear()


def start(auth: AuthConfig, redirect_uri: str, next_path: str | None, secret: bytes) -> Started:
    """The provider's sign-in address, and the short-lived cookie that ties the answer to this browser."""
    document = discovery(auth.oidc_issuer_url or "")
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    flow = sign({"t": "flow", "s": state, "n": nonce, "v": verifier, "r": redirect_uri, "next": safe_next(next_path),
                 "exp": int(time.time()) + FLOW_SECONDS}, secret)
    params = {
        "response_type": "code",
        "client_id": auth.oidc_client_id,
        "redirect_uri": redirect_uri,
        "scope": auth.oidc_scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()),
        "code_challenge_method": "S256",
    }
    endpoint = document["authorization_endpoint"]
    return Started(url=f"{endpoint}{'&' if '?' in endpoint else '?'}{urlencode(params)}", flow_cookie=flow)


def _signing_key(document: dict, kid: str | None):
    # A key id we don't know yet may be a new key after rotation: look once more before giving up.
    for fresh in (False, True):
        for key in _fetch_json(document["jwks_uri"], fresh).get("keys", []):
            if isinstance(key, dict) and key.get("use", "sig") == "sig" and (kid is None or key.get("kid") == kid):
                try:
                    return jwt.PyJWK(key).key
                except jwt.PyJWTError as error:
                    raise SignInError("provider", f"The provider's key {kid!r} can't be used: {error}") from error
    raise SignInError("provider", f"The provider has no signing key {kid!r} at {document['jwks_uri']}.")


def _exchange(auth: AuthConfig, document: dict, code: str, flow: dict) -> dict:
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": flow["r"], "code_verifier": flow["v"]}
    methods = document.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
    basic = "client_secret_basic" in methods or "client_secret_post" not in methods
    if basic:
        auth_header = httpx.BasicAuth(auth.oidc_client_id or "", auth.oidc_client_secret or "")
    else:
        auth_header = None
        data |= {"client_id": auth.oidc_client_id or "", "client_secret": auth.oidc_client_secret or ""}
    try:
        with _client() as client:
            response = client.post(document["token_endpoint"], data=data, auth=auth_header, headers={"Accept": "application/json"})
        body = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise SignInError("provider", f"The token request to {document['token_endpoint']} failed: {error}") from error
    if response.status_code != 200 or not isinstance(body, dict) or not body.get("id_token"):
        said = body.get("error_description") or body.get("error") if isinstance(body, dict) else None
        raise SignInError("provider", f"The token request answered {response.status_code}: {body}", shown=str(said)[:300] if said else None)
    return body


def verify_id_token(auth: AuthConfig, document: dict, id_token: str, nonce: str) -> dict:
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as error:
        raise SignInError("provider", f"The ID token can't be read: {error}") from error
    algorithm = header.get("alg")
    if algorithm not in _ALGORITHMS:
        raise SignInError("provider", f"The ID token is signed with {algorithm!r}, which isn't allowed.")
    key = _signing_key(document, header.get("kid"))
    try:
        claims = jwt.decode(
            id_token, key=key, algorithms=[algorithm], audience=auth.oidc_client_id, issuer=document["issuer"],
            leeway=_LEEWAY_SECONDS, options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as error:
        raise SignInError("provider", f"The ID token didn't pass the checks: {error}") from error
    audiences = claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]]
    if len(audiences) > 1 and claims.get("azp") != auth.oidc_client_id:
        raise SignInError("provider", "The ID token is for several apps and doesn't name this one as azp.")
    if not isinstance(claims.get("nonce"), str) or not hmac.compare_digest(claims["nonce"], nonce):
        raise SignInError("expired", "The ID token's nonce doesn't match this browser's sign-in.")
    return claims


def _groups(auth: AuthConfig, claims: dict) -> tuple[tuple[str, ...], bool]:
    """The person's groups, and whether the provider left them out (no claim, or too many to fit)."""
    raw = claims.get(auth.oidc_groups_claim)
    if raw is None:
        return (), True
    values = raw.split(",") if isinstance(raw, str) else raw if isinstance(raw, list) else []
    return tuple(str(value).strip() for value in values if str(value).strip()), False


def finish(auth: AuthConfig, flow_cookie: str | None, secret: bytes, code: str | None, state: str | None,
           error: str | None = None, error_description: str | None = None) -> SignedIn:
    """Checks the provider's answer and returns who signed in. Raises SignInError otherwise."""
    flow = unsign(flow_cookie, secret, "flow")
    if flow is None:
        raise SignInError("expired", "The sign-in cookie is missing, changed or older than 10 minutes.")
    if error:
        raise SignInError("provider", f"The provider answered {error}: {error_description}", shown=(error_description or error)[:300])
    if not code or not state or not hmac.compare_digest(state, flow["s"]):
        raise SignInError("expired", "The state from the provider doesn't match this browser's sign-in.")
    document = discovery(auth.oidc_issuer_url or "")
    claims = verify_id_token(auth, document, _exchange(auth, document, code, flow)["id_token"], flow["n"])
    user = next((str(claims[name]).strip() for name in ([auth.oidc_user_claim] if auth.oidc_user_claim else ["email", "preferred_username", "sub"])
                 if claims.get(name) and str(claims[name]).strip()), None)
    if not user:
        raise SignInError("provider", f"The ID token has no {auth.oidc_user_claim or 'email, preferred_username or sub'} claim.")
    groups, missing = _groups(auth, claims)
    if auth.oidc_allowed_groups and not any(group in auth.oidc_allowed_groups for group in groups):
        raise SignInError("not_allowed", f"{user} isn't in any of OPS_SIGNALS_OIDC_ALLOWED_GROUPS (groups {'not sent' if missing else list(groups)}).", shown=user[:_MAX_NAME])
    recent_groups_missing.append(missing)
    name = claims.get("name")
    return SignedIn(user=user[:_MAX_NAME], display_name=str(name)[:_MAX_NAME] if name else None, groups=groups,
                    groups_missing=missing, next_path=flow["next"])


def session_cookie(auth: AuthConfig, signed_in: SignedIn, secret: bytes) -> tuple[str, int]:
    """The session cookie and how many seconds it lasts. It keeps only the groups a list names, so it
    stays small whatever the provider sends."""
    named = set(auth.admin_groups) | set(auth.editor_groups) | set(auth.oidc_allowed_groups)
    seconds = int(auth.session_hours * 3600)
    now = int(time.time())
    payload = {"t": "session", "u": signed_in.user, "d": signed_in.display_name, "g": [group for group in signed_in.groups if group in named],
               "gm": signed_in.groups_missing, "iat": now, "exp": now + seconds}
    return sign(payload, secret), seconds


def read_session(value: str | None, secret: bytes) -> Session | None:
    payload = unsign(value, secret, "session")
    if payload is None or not isinstance(payload.get("u"), str) or not isinstance(payload.get("g"), list):
        return None
    return Session(user=payload["u"], display_name=payload.get("d"), groups=tuple(str(group) for group in payload["g"]),
                   groups_missing=bool(payload.get("gm")), expires_at=payload["exp"])


def sign_out_url(auth: AuthConfig, signed_out_url: str) -> str | None:
    """The provider's own sign-out address, coming back to signed_out_url; None if it has none."""
    try:
        endpoint = discovery(auth.oidc_issuer_url or "").get("end_session_endpoint")
    except SignInError:
        return None
    if not endpoint:
        return None
    params = urlencode({"client_id": auth.oidc_client_id, "post_logout_redirect_uri": signed_out_url})
    return f"{endpoint}{'&' if '?' in endpoint else '?'}{params}"
