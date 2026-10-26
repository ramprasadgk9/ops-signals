"""Sign in and out of the web UI with the company's identity provider (OPS_SIGNALS_AUTH_MODE=oidc;
backend/app/oidc.py, docs/web-ui-sign-in.md).

A failed sign-in sends the browser to /sign-in?error=<code>&id=<error id>; the details are logged under
that id and never shown, except a provider's own message (E4) or the person's own name (E1).
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from backend.app import oidc
from backend.app.config import AuthConfig, get_auth_config, get_security_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["sign-in"])


def site_url(request: Request, auth: AuthConfig) -> str:
    """The address people use: OPS_SIGNALS_PUBLIC_URL, else what the request (or the proxy in front) says."""
    if auth.public_url:
        return auth.public_url
    proto = (request.headers.get("X-Forwarded-Proto") or request.url.scheme).split(",")[0].strip()
    host = (request.headers.get("X-Forwarded-Host") or "").split(",")[0].strip() or request.headers.get("Host") or request.url.netloc
    return f"{proto}://{host}"


def redirect_uri(request: Request, auth: AuthConfig) -> str:
    return f"{site_url(request, auth)}{oidc.CALLBACK_PATH}"


def _ready(auth: AuthConfig) -> tuple[bytes, str | None]:
    api_token = get_security_config().api_token
    problem = oidc.setup_problem(auth, api_token) if auth.mode == "oidc" else "Company sign-in is off (OPS_SIGNALS_AUTH_MODE isn't oidc)."
    return oidc.session_secret(auth, api_token) or b"", problem


def _failed(error: oidc.SignInError, **extra: str) -> RedirectResponse:
    logger.warning("Sign-in failed (error id %s, %s): %s", error.error_id, error.code, error.detail)
    params = {"error": error.code, "id": error.error_id} | extra
    if error.shown:
        params["said"] = error.shown
    response = RedirectResponse(f"/sign-in?{urlencode(params)}", status_code=303)
    response.delete_cookie(oidc.FLOW_COOKIE, path="/")
    return response


def _secure(request: Request, auth: AuthConfig) -> bool:
    return site_url(request, auth).startswith("https://")


@router.get("/login")
def login(request: Request, next: str | None = None) -> RedirectResponse:
    auth = get_auth_config()
    secret, problem = _ready(auth)
    if problem:
        return _failed(oidc.SignInError("config", problem))
    try:
        started = oidc.start(auth, redirect_uri(request, auth), next, secret)
    except oidc.SignInError as error:
        return _failed(error)
    response = RedirectResponse(started.url, status_code=303)
    response.set_cookie(oidc.FLOW_COOKIE, started.flow_cookie, max_age=oidc.FLOW_SECONDS, path="/", httponly=True,
                        secure=_secure(request, auth), samesite="lax")
    return response


@router.get("/callback")
def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
             error_description: str | None = None) -> RedirectResponse:
    auth = get_auth_config()
    secret, problem = _ready(auth)
    if problem:
        return _failed(oidc.SignInError("config", problem))
    try:
        signed_in = oidc.finish(auth, request.cookies.get(oidc.FLOW_COOKIE), secret, code, state, error, error_description)
    except oidc.SignInError as failure:
        return _failed(failure, **({"as": failure.shown} if failure.code == "not_allowed" and failure.shown else {}))
    cookie, seconds = oidc.session_cookie(auth, signed_in, secret)
    # Groups left out of the token: say so once (screen E2) when they would have mattered.
    if signed_in.groups_missing and (auth.admin_groups or auth.editor_groups):
        target = f"/sign-in?{urlencode({'error': 'groups', 'next': signed_in.next_path})}"
    else:
        target = signed_in.next_path
    logger.info("Signed in %s through company sign-in", signed_in.user)
    response = RedirectResponse(target, status_code=303)
    response.delete_cookie(oidc.FLOW_COOKIE, path="/")
    response.set_cookie(oidc.SESSION_COOKIE, cookie, max_age=seconds, path="/", httponly=True,
                        secure=_secure(request, auth), samesite="lax")
    return response


class SignOutOut(BaseModel):
    # Where the browser goes next: the provider's sign-out page, or /signed-out.
    redirect: str


@router.post("/logout", response_model=SignOutOut)
def logout(request: Request) -> JSONResponse:
    auth = get_auth_config()
    signed_out = f"{site_url(request, auth)}/signed-out"
    target = (oidc.sign_out_url(auth, signed_out) if auth.mode == "oidc" and auth.oidc_issuer_url else None) or "/signed-out"
    response = JSONResponse(SignOutOut(redirect=target).model_dump())
    response.delete_cookie(oidc.SESSION_COOKIE, path="/")
    return response


class SignInTestOut(BaseModel):
    reachable: bool
    issuer: str | None
    redirect_uri: str
    detail: str
    test_provider: bool = False


@router.get("/test", response_model=SignInTestOut)
def test_sign_in(request: Request) -> SignInTestOut:
    """Setup check's Test sign-in: can Ops Signals reach the provider, and which address to register.
    Admins only (backend/app/roles.py)."""
    auth = get_auth_config()
    _, problem = _ready(auth)
    uri = redirect_uri(request, auth)
    if problem:
        return SignInTestOut(reachable=False, issuer=auth.oidc_issuer_url, redirect_uri=uri, detail=problem)
    try:
        oidc.discovery(auth.oidc_issuer_url or "", fresh=True)
    except oidc.SignInError as error:
        return SignInTestOut(reachable=False, issuer=auth.oidc_issuer_url, redirect_uri=uri, detail=error.detail)
    return SignInTestOut(reachable=True, issuer=auth.oidc_issuer_url, redirect_uri=uri, detail="Ops Signals can reach your provider.",
                         test_provider=oidc.is_test_provider(auth.oidc_issuer_url or ""))

