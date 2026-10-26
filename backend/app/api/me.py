"""GET /api/me - who the backend sees on this request and why: the web UI's header chip
(docs/web-ui-sign-in.md)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.app.config import get_auth_config, get_security_config
from backend.app.identity import Actor, current_actor
from backend.app.roles import pages_for

router = APIRouter(prefix="/api", tags=["identity"])


class MeOut(BaseModel):
    signed_in: bool
    name: str | None = None
    role: str | None = None
    # grafana, proxy (company sign-in), dev (OPS_SIGNALS_DEV_USER), or none
    via: str = "none"
    groups: list[str] = Field(default_factory=list)
    granted_by: str | None = None
    # OPS_SIGNALS_AUTH_MODE as the backend runs it
    mode: str
    # Set when sign-in is configured but can't work, in words for the person reading it.
    problem: str | None = None
    # Each web UI page and the lowest role that may open it (backend/app/roles.py PAGES).
    pages: dict[str, str] = Field(default_factory=dict)
    # Pages this person sees without their set-up part, e.g. Autonomous Analysis for a Viewer.
    read_only_pages: list[str] = Field(default_factory=list)


def sign_in_problem(mode: str, api_token: str | None, actor: Actor | None) -> str | None:
    if mode != "proxy-headers":
        return None
    if not api_token:
        return "Sign-in is on, but OPS_SIGNALS_API_TOKEN isn't set, so the sign-in proxy's user headers are ignored."
    if actor is None:
        return "Sign-in is on, but this request had no user header. Check that the sign-in proxy passes it to the web UI."
    return None


@router.get("/me", response_model=MeOut)
def me(actor: Actor | None = Depends(current_actor)) -> MeOut:
    auth = get_auth_config()
    problem = sign_in_problem(auth.mode, get_security_config().api_token, actor)
    if actor is None:
        pages, _ = pages_for(None)
        return MeOut(signed_in=False, mode=auth.mode, problem=problem, pages=pages)
    pages, read_only = pages_for(actor.role or "Viewer")
    return MeOut(
        signed_in=actor.name is not None,
        name=actor.name,
        role=actor.role,
        via=actor.via,
        groups=list(actor.groups),
        granted_by=actor.granted_by,
        mode=auth.mode,
        problem=problem,
        pages=pages,
        read_only_pages=read_only,
    )
