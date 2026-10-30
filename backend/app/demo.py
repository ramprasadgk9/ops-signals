"""Demo mode (OPS_SIGNALS_DEMO_MODE=true): Ops Signals as a public, shared demo site.

Visitors can look around, open and work cases, answer "Was this real?", ask the assistant and
analyze the demo's own metrics or a bundled sample. What would change the site for everyone else,
reach outside it, or take someone's own data is refused here (403, with the reason the UI shows):
set-up and lab work (the Admin requests in roles.py), schedules, deleting, uploads, Jira, and the
endpoints only the demo's own services may call (alerts, OTLP, deploy events).

Only requests that came through the web proxy are refused. The demo's own services (the seeder,
Alertmanager, the OTLP sender) call the backend directly, so they keep working; the proxy
(docker/nginx.web.conf, or one in front of it) adds X-Forwarded-For, which tells them apart.

Off by default; with it off, nothing here changes any request.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request

from backend.app.roles import required_role

DEFAULT_RUN_YOURSELF_URL = "https://github.com/ramprasadgk9/ops-signals#try-it-in-one-command"
_READ_METHODS = {"GET", "HEAD", "OPTIONS"}
# When this backend started: the hosted demo restarts it on every reset, so the next reset is a
# fixed time after it.
_STARTED_AT = datetime.now(timezone.utc)


@dataclass(frozen=True)
class DemoConfig:
    enabled: bool = False
    # How often the hosted demo is wiped and seeded again; 0 = not on a schedule (no countdown).
    reset_hours: float = 0
    run_yourself_url: str = DEFAULT_RUN_YOURSELF_URL
    # The "Things to try" guide. Always on in demo mode; OPS_SIGNALS_DEMO_TOUR shows it on its own,
    # without the banner or view-only settings (the local demo, docker-compose.demo.yml).
    tour: bool = False


def _env_on(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def get_demo_config() -> DemoConfig:
    enabled = _env_on("OPS_SIGNALS_DEMO_MODE")
    try:
        reset_hours = max(0.0, float(os.getenv("OPS_SIGNALS_DEMO_RESET_HOURS") or 0))
    except ValueError:
        reset_hours = 0.0
    url = (os.getenv("OPS_SIGNALS_DEMO_RUN_YOURSELF_URL") or "").strip() or DEFAULT_RUN_YOURSELF_URL
    return DemoConfig(enabled=enabled, reset_hours=reset_hours, run_yourself_url=url, tour=enabled or _env_on("OPS_SIGNALS_DEMO_TOUR"))


def next_reset(config: DemoConfig, now: datetime | None = None) -> datetime | None:
    """When the site resets next: the first reset period after this backend started that is still
    ahead (the reset itself restarts the backend, so normally the first one)."""
    if not config.enabled or config.reset_hours <= 0:
        return None
    period = timedelta(hours=config.reset_hours)
    now = now or datetime.now(timezone.utc)
    reset = _STARTED_AT + period
    while reset <= now:
        reset += period
    return reset


_SHARED = "Turned off in the demo: it would change the site for everyone. Run Ops Signals yourself to try it."
_TURNED_OFF: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^/api/(integrations/alertmanager|integrations/ticketing|alerts|otlp/|events)"),
     "Turned off in the demo: only the demo's own services send alerts, metrics and deploys here."),
    (re.compile(r"^/api/ingestion/csv-run$"),
     "Turned off in the demo: everyone shares this site, so you can't upload your own file. Try a sample file, or run Ops Signals yourself."),
    (re.compile(r"^/api/autonomous/policies"),
     "Turned off in the demo: schedules are shared by everyone on this site. Run Ops Signals yourself to try it."),
    (re.compile(r"^/api/cases/\d+/ticket/"),
     "Turned off in the demo: no ticketing system is connected."),
    (re.compile(r"^/api/behavior-definitions/suggestions/"), _SHARED),
]


def demo_refusal(method: str, path: str) -> str | None:
    """Why demo mode refuses this request from a visitor, or None when it's allowed."""
    method = method.upper()
    path = path.rstrip("/")
    if method == "OPTIONS":
        return None
    if required_role(method, path) == "Admin":
        return _SHARED
    if method in _READ_METHODS:
        return None
    if method == "DELETE":
        return "Turned off in the demo: nothing can be deleted here. The demo resets on its own."
    return next((reason for pattern, reason in _TURNED_OFF if pattern.search(path)), None)


def from_visitor(request: Request) -> bool:
    """The request came through the web proxy (a visitor), not from one of the demo's own services."""
    return "x-forwarded-for" in request.headers or "x-real-ip" in request.headers


def refuse_in_demo(request: Request) -> None:
    """App-wide dependency: in demo mode, refuses a visitor's request that is turned off (403)."""
    if not get_demo_config().enabled or not from_visitor(request):
        return
    reason = demo_refusal(request.method, request.url.path)
    if reason:
        raise HTTPException(status_code=403, detail=reason)
