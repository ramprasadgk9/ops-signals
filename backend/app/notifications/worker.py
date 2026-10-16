from __future__ import annotations

import asyncio
import logging

from backend.app.notifications.slack_client import SlackNotifier

logger = logging.getLogger(__name__)


async def run_slack_retry_loop(notifier: SlackNotifier, poll_interval_seconds: float = 15.0) -> None:
    """Lifespan-managed loop retrying Slack messages that didn't arrive (SlackNotifier.deliver_due)."""
    logger.info("Slack retry worker started (polling every %ss)", poll_interval_seconds)
    try:
        while True:
            try:
                await asyncio.to_thread(notifier.deliver_due)
            except Exception:
                logger.exception("Slack retry worker tick failed")
            await asyncio.sleep(poll_interval_seconds)
    except asyncio.CancelledError:
        logger.info("Slack retry worker stopped")
        raise
