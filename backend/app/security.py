"""API-wide access controls: the optional API token and the file-write switch (docs/security-model.md)."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request

from backend.app.alerts.auth import check_bearer_token
from backend.app.config import SecurityConfig, get_security_config

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
    public routes needs `Authorization: Bearer <token>`."""
    if is_public_route(request.method, request.url.path):
        return
    check_bearer_token(authorization, config.api_token)



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
