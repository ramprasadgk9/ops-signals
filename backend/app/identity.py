"""Who is asking: the Grafana user behind a request that came through the plugin's Grafana proxy.

Grafana's plugin proxy (plugin.json `routes`) adds `X-Grafana-Context`, a JSON description of the
signed-in user, and overwrites any copy the browser sent. A request made straight to the backend can
carry a made-up one, so a name read here is only as trustworthy as the backend's own access control:
with OPS_SIGNALS_API_TOKEN set, only Grafana (which holds the token) and token holders can call at
all (docs/security-model.md). Requests without the header have no actor: the web UI, scripts and the
plugin in "Browser, directly" mode record no name.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from fastapi import Request

logger = logging.getLogger(__name__)

GRAFANA_CONTEXT_HEADER = "X-Grafana-Context"
_MAX_NAME = 128
_ROLES = {"Viewer", "Editor", "Admin"}


@dataclass(frozen=True)
class Actor:
    """name is what the UI shows and records ("priya"); None for Grafana's anonymous visitor."""

    name: str | None
    role: str | None
    via: str = "grafana"


def actor_from_context(raw: str | None) -> Actor | None:
    if not raw:
        return None
    try:
        context = json.loads(raw)
    except ValueError:
        logger.warning("Ignoring an %s header that is not JSON", GRAFANA_CONTEXT_HEADER)
        return None
    if not isinstance(context, dict):
        return None
    role = context.get("OrgRole") if context.get("OrgRole") in _ROLES else None
    anonymous = bool(context.get("IsAnonymous")) or not (context.get("Login") or context.get("Email"))
    if anonymous:
        return Actor(name=None, role=role)
    name = next((str(value).strip() for value in (context.get("Login"), context.get("Name"), context.get("Email")) if value and str(value).strip()), None)
    return Actor(name=name[:_MAX_NAME] if name else None, role=role)


def current_actor(request: Request) -> Actor | None:
    """FastAPI dependency: the Grafana user behind this request, or None when it didn't come through Grafana."""
    return actor_from_context(request.headers.get(GRAFANA_CONTEXT_HEADER))


def actor_name(actor: Actor | None) -> str | None:
    # Only a real Actor: the MCP server calls endpoint functions directly, leaving the parameter at
    # FastAPI's Depends(...) default.
    return actor.name if isinstance(actor, Actor) else None
