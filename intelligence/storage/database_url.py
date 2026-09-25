from __future__ import annotations

import os

DATABASE_URL_ENV = "OPS_SIGNALS_DATABASE_URL"
# The name before the project settled on the OPS_SIGNALS_ prefix; still honoured so existing
# compose files, Helm values and .env files keep working.
LEGACY_DATABASE_URL_ENV = "OPS_INTEL_DATABASE_URL"


def database_url_from_env() -> str | None:
    """The database URL from the environment (new name first), or None when neither is set."""
    for name in (DATABASE_URL_ENV, LEGACY_DATABASE_URL_ENV):
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None
