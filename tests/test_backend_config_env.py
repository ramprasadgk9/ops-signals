from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Imports backend.app.config with a stand-in `dotenv` module that records any load_dotenv call,
# and with every ".env" reported as present, so a guarded `if .env exists: load` would still fire.
_PROBE = """
import pathlib, sys, types
_is_file = pathlib.Path.is_file
pathlib.Path.is_file = lambda self: self.name == ".env" or _is_file(self)
calls = []
stub = types.ModuleType("dotenv")
stub.load_dotenv = lambda *args, **kwargs: calls.append((args, kwargs)) or True
sys.modules["dotenv"] = stub
import backend.app.config
print("LOAD_DOTENV_CALLS", len(calls))
"""


def test_backend_config_never_loads_dotenv_itself() -> None:
    """Settings come from the process environment only. A repo-root .env loaded with override on
    import replaced explicitly set variables, including the test suite's own (and a developer's
    .env can hold a real Slack webhook). scripts/run_all.sh already sources .env for the dev stack."""
    result = subprocess.run([sys.executable, "-c", _PROBE], cwd=ROOT, capture_output=True, text=True, timeout=120)

    assert result.returncode == 0, result.stderr
    assert "LOAD_DOTENV_CALLS 0" in result.stdout
