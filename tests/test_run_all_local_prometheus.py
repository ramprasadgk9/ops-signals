"""scripts/run_all.sh starts the bundled Prometheus and mock metrics only while Ops Signals reads them:
not once .env points it at your own Prometheus or Mimir."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "lib" / "local_prometheus.sh"
_VARS = (
    "OPS_SIGNALS_PROMETHEUS_URL",
    "OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE",
    "OPS_SIGNALS_LOCAL_PROMETHEUS",
    "OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED",
)


def _starts_local_prometheus(**env: str) -> bool:
    clean = {key: value for key, value in os.environ.items() if key not in _VARS}
    result = subprocess.run(
        ["bash", "-c", f'source "{HELPER}"; if wants_local_prometheus; then echo yes; else echo no; fi'],
        env={**clean, **env}, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip() == "yes"


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"OPS_SIGNALS_PROMETHEUS_URL": ""},
        # The value .env.example ships with.
        {"OPS_SIGNALS_PROMETHEUS_URL": "http://localhost:9090"},
        {"OPS_SIGNALS_PROMETHEUS_URL": "http://127.0.0.1:9090/"},
        # Alert enrichment's demo rules run in the bundled Prometheus.
        {"OPS_SIGNALS_PROMETHEUS_URL": "https://prom.example.com", "OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED": "true"},
        {"OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE": "prometheus-connections.yaml", "OPS_SIGNALS_LOCAL_PROMETHEUS": "true"},
    ],
)
def test_bundled_prometheus_starts_while_it_is_what_ops_signals_reads(env: dict[str, str]) -> None:
    assert _starts_local_prometheus(**env)


@pytest.mark.parametrize(
    "env",
    [
        {"OPS_SIGNALS_PROMETHEUS_URL": "https://prom.example.com"},
        {"OPS_SIGNALS_PROMETHEUS_URL": "http://localhost:9009/prometheus"},
        {"OPS_SIGNALS_PROMETHEUS_URL": "http://localhost:9090", "OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE": "prometheus-connections.yaml"},
        {"OPS_SIGNALS_LOCAL_PROMETHEUS": "false"},
    ],
)
def test_bundled_prometheus_is_skipped_for_your_own_prometheus_or_mimir(env: dict[str, str]) -> None:
    assert not _starts_local_prometheus(**env)
