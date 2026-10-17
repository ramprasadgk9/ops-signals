"""Indexes cases that should be in operational memory but aren't.

A case created while Qdrant was down, or while memory couldn't start, stayed `not_indexed` (or
`failed`) for good: nothing retried it, and similar-case search, "this fix worked before" and
alert context quietly missed it. This runs at startup and then every few minutes.

Which cases: with automatic indexing on creation, cases `not_indexed` or `failed` that the user
didn't remove (memory_opted_out); with automatic indexing on update, `stale` ones too. A case left
`indexing` by a crash counts only at startup, when no indexing can be running.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.config import MemoryConfig
from backend.app.memory.indexer import CaseMemoryIndexer
from backend.app.models.entities import OperationalCaseEntity

logger = logging.getLogger(__name__)

CATCH_UP_INTERVAL_SECONDS = 300
CATCH_UP_BATCH_SIZE = 50


def _waiting_statuses(config: MemoryConfig, *, at_startup: bool) -> set[str]:
    statuses: set[str] = set()
    if config.indexing.automatic_on_case_creation:
        statuses |= {"not_indexed", "failed"}
        if at_startup:
            statuses.add("indexing")
    if config.indexing.automatic_on_case_update:
        statuses.add("stale")
    return statuses


def _waiting(config: MemoryConfig, *, at_startup: bool = False):
    statuses = _waiting_statuses(config, at_startup=at_startup)
    return OperationalCaseEntity.memory_status.in_(statuses), OperationalCaseEntity.memory_opted_out.is_(False)


def count_waiting(db: Session, config: MemoryConfig | None) -> int:
    """Cases catch-up indexing will add to memory; 0 when memory or automatic indexing is off."""
    if not config or not config.enabled or not _waiting_statuses(config, at_startup=False):
        return 0
    return int(db.scalar(select(func.count()).select_from(OperationalCaseEntity).where(*_waiting(config))) or 0)


def catch_up_case_memory(db: Session, indexer: CaseMemoryIndexer, config: MemoryConfig, *, at_startup: bool = False) -> int:
    """Indexes up to CATCH_UP_BATCH_SIZE waiting cases; returns how many made it into memory.
    Stops at the first failure: the vector store is most likely down, and the rest can wait."""
    if not config.enabled or not _waiting_statuses(config, at_startup=at_startup):
        return 0
    cases = db.scalars(
        select(OperationalCaseEntity)
        .where(*_waiting(config, at_startup=at_startup))
        .order_by(OperationalCaseEntity.id)
        .limit(CATCH_UP_BATCH_SIZE)
    ).all()
    indexed = 0
    for case in cases:
        try:
            indexer.index_case(case, db)
        except Exception as exc:
            logger.warning("Memory catch-up stopped at case %s; will retry later: %s", case.id, exc)
            break
        indexed += 1
    if indexed:
        logger.info("Memory catch-up indexed %d case(s)", indexed)
    return indexed


def _catch_up_once(session_local, indexer: CaseMemoryIndexer, config: MemoryConfig, at_startup: bool) -> int:
    with session_local() as db:
        return catch_up_case_memory(db, indexer, config, at_startup=at_startup)


def waiting_at_startup(session_local, config: MemoryConfig) -> bool:
    """Whether anything needs catching up right away, so a normal startup runs nothing."""
    try:
        with session_local() as db:
            return bool(
                db.scalar(select(func.count()).select_from(OperationalCaseEntity).where(*_waiting(config, at_startup=True)))
            )
    except Exception:
        logger.warning("Could not check for cases waiting to be indexed", exc_info=True)
        return False


async def run_memory_catch_up_loop(indexer: CaseMemoryIndexer, config: MemoryConfig, session_local, *, run_now: bool) -> None:
    """Lifespan-managed: at startup when run_now (see waiting_at_startup), then every
    CATCH_UP_INTERVAL_SECONDS for cases an outage keeps out of memory while the backend runs."""
    at_startup = True
    if not run_now:
        at_startup = False
        await asyncio.sleep(CATCH_UP_INTERVAL_SECONDS)
    while True:
        try:
            await asyncio.to_thread(_catch_up_once, session_local, indexer, config, at_startup)
        except Exception:
            logger.exception("Memory catch-up tick failed")
        at_startup = False
        await asyncio.sleep(CATCH_UP_INTERVAL_SECONDS)
