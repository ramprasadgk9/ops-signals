from __future__ import annotations

import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import distinct, select, text
from sqlalchemy.orm import Session

from backend.app.models.db import get_db, get_engine
from backend.app.models.entities import NormalizedPoint

router = APIRouter(prefix="/api", tags=["catalog"])

# /api/health answered "ok" while Postgres was down, so Docker and the Helm readiness probe kept
# sending traffic to a backend that failed every real request. It now checks the database, but
# never waits longer than this: an unreachable host can hold a connection attempt for a minute.
DATABASE_CHECK_TIMEOUT_SECONDS = float(os.getenv("OPS_SIGNALS_HEALTH_DB_TIMEOUT_SECONDS", "2"))

# One check at a time: while one hangs, later health calls wait on it rather than start more.
_check_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="health-db")
_check_lock = threading.Lock()
_pending_check: Future | None = None


def _ping_database() -> None:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))


def database_reachable(timeout_seconds: float | None = None) -> bool:
    global _pending_check
    with _check_lock:
        if _pending_check is None or _pending_check.done():
            _pending_check = _check_executor.submit(_ping_database)
        check = _pending_check
    try:
        check.result(timeout=DATABASE_CHECK_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds)
    except Exception:
        return False
    return True


@router.get("/health")
def health():
    """Readiness: the backend and its database. 503 when the database can't be reached, so load
    balancers and orchestrators stop routing to a backend that can't serve."""
    if database_reachable():
        return {"status": "ok", "database": "ok"}
    return JSONResponse(status_code=503, content={"status": "degraded", "database": "unavailable"})


@router.get("/health/live")
def liveness() -> dict[str, str]:
    """Liveness: the process is up and answering, whatever its dependencies are doing. Restarting
    the backend doesn't fix a database outage, so a liveness probe should use this, not /api/health."""
    return {"status": "ok"}


@router.get("/services")
def list_services(db: Session = Depends(get_db)) -> list[str]:
    rows = db.execute(select(distinct(NormalizedPoint.service))).all()
    return [row[0] for row in rows if row[0]]


@router.get("/services/{service}/metrics")
def list_metrics(service: str, db: Session = Depends(get_db)) -> list[str]:
    rows = db.execute(
        select(distinct(NormalizedPoint.metric_name)).where(NormalizedPoint.service == service)
    ).all()
    return [row[0] for row in rows if row[0]]
