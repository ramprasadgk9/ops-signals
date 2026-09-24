from __future__ import annotations

import hmac

from fastapi import HTTPException


def check_bearer_token(authorization: str | None, expected: str | None) -> None:
    """Optional shared-secret auth for the write endpoints: a no-op when no token is configured
    (keeps the local demo frictionless), 401 otherwise unless `Authorization: Bearer <token>`."""
    if not expected:
        return
    if not authorization or not hmac.compare_digest(authorization, f"Bearer {expected}"):
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")
