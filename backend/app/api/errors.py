"""Error responses that don't leak internals.

Error details used to go straight into the response: a database outage returned the full driver
message with host and port. The details now go to the server log under a short id, and the
response names that id so an operator can find them.

An outage of a dependency is a 503 that names it, not a 500 "something failed": the database being
unreachable, or (from memory endpoints) Qdrant being unreachable, is something an operator can act
on, and a client or a health probe can retry it."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import exc as sa_exc

logger = logging.getLogger(__name__)

DATABASE_UNAVAILABLE = "The database is unavailable right now"
MEMORY_UNAVAILABLE = "Operational memory is unavailable right now: Qdrant can't be reached"


def _chain(exc: BaseException) -> Iterator[BaseException]:
    """`exc`, what caused it, and a SQLAlchemy error's driver exception (`.orig`)."""
    seen: set[int] = set()
    pending: list[BaseException] = [exc]
    while pending:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        for linked in (getattr(current, "orig", None), current.__cause__, current.__context__):
            if isinstance(linked, BaseException):
                pending.append(linked)


def is_database_unavailable(exc: BaseException) -> bool:
    """The database can't be reached (refused, dropped, pool invalidated) - not a SQL error. SQLite
    raises OperationalError for mistakes like a missing table too, so only a disconnect SQLAlchemy
    recognised, a pool invalidation, or psycopg's own connection-level error count."""
    for item in _chain(exc):
        if isinstance(item, sa_exc.InvalidatePoolError):
            return True
        if isinstance(item, sa_exc.DBAPIError) and item.connection_invalidated:
            return True
        if type(item).__module__.startswith("psycopg") and type(item).__name__ == "OperationalError":
            return True
    return False


def is_connection_failure(exc: BaseException) -> bool:
    """A network-level failure reaching a service: refused, timed out, dropped."""
    for item in _chain(exc):
        if isinstance(item, (httpx.TransportError, ConnectionError, TimeoutError)):
            return True
        if type(item).__name__ == "ResponseHandlingException" and type(item).__module__.startswith("qdrant_client"):
            return True
    return False


def _logged(message: str, exc: BaseException) -> str:
    error_id = uuid.uuid4().hex[:8]
    logger.error("%s (error %s)", message, error_id, exc_info=exc)
    return error_id


def internal_error(message: str, exc: BaseException) -> HTTPException:
    """Logs `exc` with its traceback and returns an error that says only `message` and the log id:
    a 503 when the database is unreachable, otherwise a 500."""
    error_id = _logged(message, exc)
    if is_database_unavailable(exc):
        return HTTPException(status_code=503, detail=f"{DATABASE_UNAVAILABLE}. Details are in the server log (error {error_id}).")
    return HTTPException(status_code=500, detail=f"{message}. Details are in the server log (error {error_id}).")


def memory_error(message: str, exc: BaseException) -> HTTPException:
    """internal_error for endpoints that talk to Qdrant: a connection failure there means operational
    memory is down (QA-34 - it used to read "Search failed", a 500, while the sidebar said Healthy)."""
    if is_connection_failure(exc) and not is_database_unavailable(exc):
        error_id = _logged(message, exc)
        return HTTPException(status_code=503, detail=f"{MEMORY_UNAVAILABLE}. Details are in the server log (error {error_id}).")
    return internal_error(message, exc)


def memory_not_ready(fallback: str) -> HTTPException:
    """503 for a memory endpoint whose services never came up: why, in plain words, when memory is
    still starting or can't reach Qdrant ("Similarity service not initialized" told a user nothing),
    otherwise `fallback`."""
    from backend.app.memory import availability

    if availability.status() in {availability.UNAVAILABLE, availability.STARTING}:
        return HTTPException(status_code=503, detail=availability.unavailable_reason())
    return HTTPException(status_code=503, detail=fallback)


async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    """Last resort for an exception no endpoint handled: the same JSON shape and log id as
    internal_error, instead of Starlette's plain-text "Internal Server Error" (QA-38)."""
    error = internal_error(f"{request.method} {request.url.path} failed", exc)
    return JSONResponse(status_code=error.status_code, content={"detail": error.detail})
