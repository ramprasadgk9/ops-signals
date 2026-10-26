"""API-wide access controls: the optional API token and the file-write switch (docs/security-model.md)."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Depends, Header, HTTPException, Request

from backend.app import oidc
from backend.app.alerts.auth import check_bearer_token
from backend.app.config import SecurityConfig, get_auth_config, get_security_config

# Reachable without the API token. Health stays open for load balancers and container checks; the
# receivers are called by Alertmanager and CI/CD systems and check their own tokens instead (falling
# back to the API token - see receiver_token_or_api_token).
PUBLIC_ROUTES = frozenset(
    {
        ("GET", "/api/health"),
        ("GET", "/api/health/live"),
        ("POST", "/api/integrations/alertmanager"),
        ("POST", "/api/alerts"),
        ("POST", "/api/events"),
    }
)


# With the backend's own sign-in (OPS_SIGNALS_AUTH_MODE=oidc) a browser has no token yet: it needs these
# to find out it isn't signed in and to sign in or out.
SIGN_IN_ROUTES = frozenset(
    {
        ("GET", "/api/me"),
        ("GET", oidc.LOGIN_PATH),
        ("GET", oidc.CALLBACK_PATH),
        ("POST", "/api/auth/logout"),
    }
)
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def is_public_route(method: str, path: str) -> bool:
    normalized = path.rstrip("/")
    if (method, normalized) in PUBLIC_ROUTES:
        return True
    if method == "POST" and normalized.startswith("/api/integrations/ticketing/") and normalized.endswith("/webhook"):
        return True
    return False


def require_api_token(
    request: Request,
    authorization: str | None = Header(default=None),
    config: SecurityConfig = Depends(get_security_config),
) -> None:
    """App-wide dependency: a no-op until OPS_SIGNALS_API_TOKEN is set, then every route outside
    public routes needs `Authorization: Bearer <token>` - or, with the backend's own sign-in, a valid
    session cookie (backend/app/oidc.py)."""
    if is_public_route(request.method, request.url.path):
        return
    auth = get_auth_config()
    if auth.mode == "oidc" and authorization is None:
        if (request.method, request.url.path.rstrip("/")) in SIGN_IN_ROUTES:
            return
        secret = oidc.session_secret(auth, config.api_token)
        if secret and not oidc.setup_problem(auth, config.api_token) and oidc.read_session(request.cookies.get(oidc.SESSION_COOKIE), secret):
            require_same_site(request, auth.public_url, config.cors_origins)
            return
    check_bearer_token(authorization, config.api_token)


def site_origins(request: Request, public_url: str | None) -> set[str]:
    """The addresses this site answers on: OPS_SIGNALS_PUBLIC_URL, and the one the request came to
    (as the proxy in front reports it)."""
    proto = (request.headers.get("X-Forwarded-Proto") or request.url.scheme).split(",")[0].strip()
    hosts = {request.headers.get("Host"), (request.headers.get("X-Forwarded-Host") or "").split(",")[0].strip()}
    origins = {f"{proto}://{host}" for host in hosts if host}
    if public_url:
        parts = urlsplit(public_url)
        origins.add(f"{parts.scheme}://{parts.netloc}")
    return origins


def require_same_site(request: Request, public_url: str | None, cors_origins: list[str]) -> None:
    """A change carried by the session cookie must come from this site's own pages (no cross-site
    request forgery): its Origin, or else its Referer, is one of the site's addresses."""
    if request.method not in _UNSAFE_METHODS:
        return
    sent = request.headers.get("Origin") or request.headers.get("Referer")
    if sent:
        parts = urlsplit(sent)
        if f"{parts.scheme}://{parts.netloc}" in site_origins(request, public_url) | set(cors_origins):
            return
    raise HTTPException(status_code=403, detail="This change didn't come from an Ops Signals page. Reload the page and try again.")



def receiver_token_or_api_token(receiver_token: str | None) -> str | None:
    """A receiver with no token of its own is protected by the API token, so setting only
    OPS_SIGNALS_API_TOKEN never leaves the receivers open."""
    return receiver_token or get_security_config().api_token


def require_file_writes(config: SecurityConfig = Depends(get_security_config)) -> None:
    """Guards endpoints that write or delete files on the server (analyzer registrations, generated
    adapter code, behavior-definition packs)."""
    if not config.allow_file_writes:
        raise HTTPException(
            status_code=403,
            detail="Writing files on the server is disabled. Set OPS_SIGNALS_ALLOW_FILE_WRITES=true to enable it.",
        )
