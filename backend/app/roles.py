"""What each role may change: the Grafana role for requests through the plugin's Grafana proxy, or
the role the company's groups give for the web UI behind a sign-in proxy (backend/app/identity.py).

The role is the Grafana user's org role from X-Grafana-Context (backend/app/identity.py), which Grafana
sets and a browser can't override. Reading is open to every role, except set-up details and analyzer
lab work, kept for Admins. A change needs an Editor, except a few read-like requests open to Viewers
(asking, previewing, testing a connection) and set-up and lab actions kept for Admins. Requests that don't come through Grafana carry no role and are not limited
here: the API token (backend/app/security.py) is what protects those (docs/security-model.md).
Requests with no actor at all (no Grafana, no sign-in) are not limited here either.
"""

from __future__ import annotations

import re

from fastapi import HTTPException, Request

from backend.app.identity import current_actor

RANKS = {"Viewer": 1, "Editor": 2, "Admin": 3}
_READ_METHODS = {"GET", "HEAD", "OPTIONS"}
# Who hands out roles: Grafana's admin for the plugin, the company's groups for the web UI.
_ASK_EDITOR = {"grafana": "Ask your Grafana admin for the Editor role."}
_ASK_EDITOR_ELSEWHERE = "Ask your Ops Signals admin for the Editor role."
_ADMIN_ONLY = {"grafana": "Only Grafana admins can do this."}
_ADMIN_ONLY_ELSEWHERE = "Only Ops Signals admins can do this."
_ADMIN_SEES = {"grafana": "Only Grafana admins can see this."}
_ADMIN_SEES_ELSEWHERE = "Only Ops Signals admins can see this."

# Changes nothing, or only the asker's own rating of an answer: open to Viewers.
_VIEWER_WRITES = [re.compile(pattern) for pattern in (
    r"^/api/autonomous/preview$",
    r"^/api/autonomous/questions/answer$",
    r"^/api/questions/answer$",
    r"^/api/assistant/chat$",
    r"^/api/assistant/feedback(/\d+)?$",
    r"^/api/memory/chat$",
    r"^/api/mcp/(assistant/chat|memory/chat|questions/answer|metric-analyzer-recommendations/evaluate)$",
    r"^/api/prometheus/(preview|test-connection)$",
    r"^/api/cases/\d+/(rca|resolution|writeup)/suggest$",
    r"^/api/findings/\d+/suggested-fixes/runbook-draft$",
    r"^/api/(cases|findings)/\d+/fix-came-back/why$",
    r"^/api/metric-usage/drop-config$",
    r"^/api/auth/logout$",
)]

# Set-up, labs and data management: Admins only.
_ADMIN_WRITES = [re.compile(pattern) for pattern in (
    r"^/api/testing/",
    r"^/api/admin/",
    r"^/api/analyzer-labs/",
    r"^/api/behavior-definitions/(save-to-pack|suggestions/)",
    r"^/api/assistant/(docs-check/tests|knowledge/bootstrap)$",
    r"^/api/case-imports",
    r"^/api/integrations/alertmanager/test$",
    r"^/api/ai/test$",
    r"^/api/metric-usage/run$",
)]

# Set-up details (addresses, which secrets are set, how to fix) and unreleased analyzer work: Admins
# only. Everyone else gets GET /api/setup/summary for the setup reminder and the plugin's header chips.
_ADMIN_READS = [re.compile(pattern) for pattern in (
    r"^/api/setup/check$",
    r"^/api/auth/test$",
    r"^/api/admin/",
    r"^/api/analyzer-labs/",
    r"^/api/case-imports",
)]

# Why a Viewer can't, in the words the plugin shows next to a locked button.
_EDITOR_REASONS = [
    (re.compile(r"^/api/findings/\d+/feedback$"), "Editors answer \"Was this real?\", because it changes the trust numbers for everyone."),
    (re.compile(r"^/api/(mcp/)?cases/"), "Editors can create and work on cases."),
    (re.compile(r"^/api/autonomous/policies"), "Editors can change schedules."),
    (re.compile(r"^/api/(autonomous/run-once|analysis/|ingestion/)"), "Editors can run analyses."),
]


# The web UI pages each role may open, by the lowest role (frontend/src/routes/AppRoutes.tsx). An
# entry covers its own address and the ones under it, except "/", which is only Overview. A page not
# listed here is for Admins, so a new page starts closed until it is added.
PAGES: dict[str, str] = {
    "/": "Viewer",
    "/alerts": "Viewer",
    "/findings": "Viewer",
    "/signals": "Viewer",
    "/questions": "Viewer",
    "/cases": "Viewer",
    "/metric-usage": "Viewer",
    "/behavior-intelligence": "Viewer",
    "/recurring-problems": "Viewer",
    "/assistant": "Viewer",
    "/memory-chat": "Viewer",
    "/autonomous-monitoring": "Viewer",
    "/validate-data": "Editor",
    "/analyzer-recommendation": "Editor",
    "/integrations": "Admin",
    "/experiments": "Admin",
    "/analyzer-router": "Admin",
    "/assistant/docs-check": "Admin",
    "/capabilities": "Admin",
    "/settings": "Admin",
    "/setup-check": "Admin",
}

# Pages a role opens without their set-up part, by the highest role that gets it so.
READ_ONLY_PAGES: dict[str, str] = {
    "/autonomous-monitoring": "Viewer",
}


def _page_entry(path: str) -> str | None:
    """The PAGES entry that covers this address: the longest one."""
    covering = [entry for entry in PAGES if path == entry or (entry != "/" and path.startswith(f"{entry}/"))]
    return max(covering, key=len, default=None)


def page_role(path: str) -> str:
    """The lowest role that may open this web UI page."""
    entry = _page_entry(path.rstrip("/") or "/")
    return PAGES[entry] if entry else "Admin"


def pages_for(role: str | None) -> tuple[dict[str, str], list[str]]:
    """What /api/me tells the web UI: every page with its role, and the pages this role sees read-only.
    With no role (no sign-in) nothing is read-only."""
    if role is None:
        return dict(PAGES), []
    return dict(PAGES), [page for page, upto in READ_ONLY_PAGES.items() if RANKS.get(role, 0) <= RANKS[upto]]


def required_role(method: str, path: str) -> str | None:
    """The lowest role that may make this request, or None when any role may."""
    normalized = path.rstrip("/")
    if method.upper() == "OPTIONS":
        return None
    if method.upper() in _READ_METHODS:
        return "Admin" if any(pattern.search(normalized) for pattern in _ADMIN_READS) else None
    if any(pattern.search(normalized) for pattern in _ADMIN_WRITES):
        return "Admin"
    if any(pattern.search(normalized) for pattern in _VIEWER_WRITES):
        return None
    return "Editor"


def refusal(path: str, needed: str, via: str = "grafana", reading: bool = False) -> str:
    if needed == "Admin" and reading:
        return _ADMIN_SEES.get(via, _ADMIN_SEES_ELSEWHERE)
    if needed == "Admin":
        return _ADMIN_ONLY.get(via, _ADMIN_ONLY_ELSEWHERE)
    reason = next((text for pattern, text in _EDITOR_REASONS if pattern.search(path)), "Editors can change things in Ops Signals.")
    return f"{reason} {_ASK_EDITOR.get(via, _ASK_EDITOR_ELSEWHERE)}"


def require_grafana_role(request: Request) -> None:
    """App-wide dependency: refuses a change the Grafana user's role doesn't allow (403)."""
    actor = current_actor(request)
    if actor is None:
        return
    needed = required_role(request.method, request.url.path)
    if needed is None:
        return
    if RANKS.get(actor.role or "", 0) < RANKS[needed]:
        reading = request.method.upper() in _READ_METHODS
        raise HTTPException(status_code=403, detail=refusal(request.url.path.rstrip("/"), needed, actor.via, reading))
