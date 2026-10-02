"""Background worker loop for the Pluggable Case Ticketing Architecture.

Offloads all synchronous database and Jira HTTP operations onto worker threads
via asyncio.to_thread, guaranteeing FastAPI's event loop is never blocked.
"""

from __future__ import annotations

import asyncio
import logging

from backend.app.integrations.ticketing.service import CaseTicketing

logger = logging.getLogger(__name__)


async def run_ticketing_worker_loop(
    service: CaseTicketing,
    poll_interval_seconds: int = 5,
) -> None:
    """Lifespan-managed polling loop driving outbox processing and expired lease sweeps."""
    logger.info("Case ticketing worker started (polling every %ss)", poll_interval_seconds)
    try:
        while True:
            try:
                # 1. Sweep expired create operations to ambiguous_outcome
                await asyncio.to_thread(service.sweep_expired_creates)
            except Exception:
                logger.exception("Ticketing worker sweep_expired_creates failed")

            try:
                # 2. Process pending/failed operations and expired sync operations
                await asyncio.to_thread(service.process_pending_operations)
            except Exception:
                logger.exception("Ticketing worker process_pending_operations failed")

            await asyncio.sleep(poll_interval_seconds)
    except asyncio.CancelledError:
        logger.info("Case ticketing worker stopped")
        raise
