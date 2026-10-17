"""500 responses that don't leak internals.

Error details used to go straight into the response: a database outage returned the full driver
message with host and port. The details now go to the server log under a short id, and the
response names that id so an operator can find them."""

from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def internal_error(message: str, exc: BaseException) -> HTTPException:
    """Logs `exc` with its traceback and returns a 500 that says only `message` and the log id."""
    error_id = uuid.uuid4().hex[:8]
    logger.error("%s (error %s)", message, error_id, exc_info=exc)
    return HTTPException(status_code=500, detail=f"{message}. Details are in the server log (error {error_id}).")
