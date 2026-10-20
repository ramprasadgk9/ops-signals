"""Who is asking: the Grafana user behind a request that came through the plugin's Grafana proxy, or
the person the company's sign-in proxy put in front of the web UI says signed in (docs/web-ui-sign-in.md).

Grafana's plugin proxy (plugin.json `routes`) adds `X-Grafana-Context`, a JSON description of the
signed-in user, and overwrites any copy the browser sent. A request made straight to the backend can
carry a made-up one, so a name read here is only as trustworthy as the backend's own access control:
with OPS_SIGNALS_API_TOKEN set, only Grafana (which holds the token) and token holders can call at
all (docs/security-model.md).

Without that header, OPS_SIGNALS_AUTH_MODE=proxy-headers reads the sign-in proxy's user and groups
headers - only with an API token set, since only the web UI's nginx holds it (and strips any
X-Grafana-Context a browser sends). OPS_SIGNALS_DEV_USER pretends to be someone, only without a token.
Anything else - scripts, Alertmanager, the plugin in "Browser, directly" mode - has no actor.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from fastapi import Request

from backend.app.config import AuthConfig, get_auth_config, get_security_config

logger = logging.getLogger(__name__)

GRAFANA_CONTEXT_HEADER = "X-Grafana-Context"
_MAX_NAME = 128
_ROLES = {"Viewer", "Editor", "Admin"}


@dataclass(frozen=True)
class Actor:
    """name is what the UI shows and records ("priya"); None for Grafana's anonymous visitor."""

    name: str | None
    role: str | None
    # grafana (the plugin's Grafana proxy), proxy (the company sign-in proxy) or dev (OPS_SIGNALS_DEV_USER).
    via: str = "grafana"
    groups: tuple[str, ...] = ()
    # The group that gave the role, for "Editor because of group sre".
    granted_by: str | None = None


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


def proxy_actor(headers, auth: AuthConfig, api_token: str | None) -> Actor | None:
    """Who the sign-in proxy (or, for trying it locally, OPS_SIGNALS_DEV_USER) says this is."""
    if auth.dev_user and not api_token:
        name, _, role = auth.dev_user.partition(":")
        role = role.strip().capitalize()
        return Actor(name=name.strip()[:_MAX_NAME] or "dev", role=role if role in _ROLES else "Viewer", via="dev")
    if auth.mode != "proxy-headers" or not api_token:
        return None
    user = (headers.get(auth.user_header) or "").strip()
    if not user:
        return None
    groups = tuple(group.strip() for group in re.split(r"[,;]", headers.get(auth.groups_header) or "") if group.strip())
    admin = next((group for group in groups if group in auth.admin_groups), None)
    editor = next((group for group in groups if group in auth.editor_groups), None)
    role, granted_by = ("Admin", admin) if admin else ("Editor", editor) if editor else ("Viewer", None)
    return Actor(name=user[:_MAX_NAME], role=role, via="proxy", groups=groups, granted_by=granted_by)


def current_actor(request: Request) -> Actor | None:
    """FastAPI dependency: the Grafana user (through the plugin's proxy) or the signed-in person (through
    the company sign-in proxy) behind this request, or None for neither."""
    grafana = actor_from_context(request.headers.get(GRAFANA_CONTEXT_HEADER))
    if grafana is not None:
        return grafana
    return proxy_actor(request.headers, get_auth_config(), get_security_config().api_token)


def actor_name(actor: Actor | None) -> str | None:
    # Only a real Actor: the MCP server calls endpoint functions directly, leaving the parameter at
    # FastAPI's Depends(...) default.
    return actor.name if isinstance(actor, Actor) else None
