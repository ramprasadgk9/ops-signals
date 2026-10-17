"""Whether operational memory is up, and the reason to give when it isn't.

When Qdrant was unreachable at startup, memory stayed off until a restart while /api/memory/health
said "initializing" forever and every memory feature said memory was "not enabled". The backend now
keeps retrying (see backend/app/main.py), and this records where that stands.
"""

from __future__ import annotations

DISABLED = "disabled"
STARTING = "starting"
UNAVAILABLE = "unavailable"
READY = "ready"

_state = {"status": DISABLED}


def mark(status: str) -> None:
    _state["status"] = status


def status() -> str:
    return _state["status"]


def unavailable_reason(consequence: str | None = None) -> str:
    """Why a memory feature can't answer, e.g. unavailable_reason("past cases can't be searched")."""
    if _state["status"] == UNAVAILABLE:
        reason = "Operational memory can't reach its vector store right now"
        suffix = "; Ops Signals keeps retrying."
    elif _state["status"] == STARTING:
        reason = "Operational memory is still starting"
        suffix = "."
    else:
        reason = "Operational memory is not enabled"
        suffix = "."
    return f"{reason}, so {consequence}{suffix}" if consequence else f"{reason}{suffix}"
