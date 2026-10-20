from __future__ import annotations

import io
import random
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app


def _csv(values: list[float]) -> bytes:
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    rows = ["timestamp,metric_name,value"]
    for index, value in enumerate(values):
        rows.append(f"{(start + timedelta(minutes=5 * index)).strftime('%Y-%m-%dT%H:%M:%SZ')},cpu_usage,{value:.3f}")
    return "\n".join(rows).encode("utf-8")


def _noise(points: int, seed: int) -> list[float]:
    rng = random.Random(seed)
    return [50.0 + rng.gauss(0, 1.5) for _ in range(points)]


def _validate(values: list[float]) -> dict:
    app = create_app("sqlite+pysqlite:///:memory:")
    data = {"provider": "generic", "analyzer_id": "all", "service": "checkout", "metric_name": "cpu_usage"}
    with TestClient(app) as client:
        response = client.post(
            "/api/ingestion/csv-validate",
            data=data,
            files={"file": ("upload.csv", io.BytesIO(_csv(values)), "text/csv")},
        )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("from_end", [1, 2])
def test_a_spike_in_the_newest_points_is_reported(from_end: int) -> None:
    # QA-31: the router waited for the jump to come back down before calling it a spike, so a spike
    # in a window ending "now" never got a spike detector and went unreported.
    values = _noise(288, seed=11)
    values[-from_end] = 95.0

    payload = _validate(values)

    assert "pyod_outlier" in payload["executed_analyzers"]
    assert payload["findings"], payload["executed_analyzers"]


@pytest.mark.parametrize("points", [20, 40, 49])
def test_a_spike_in_a_series_too_short_for_pyod_is_reported_by_zscore(points: int) -> None:
    # QA-29: PyOD Outlier needs 50 points and nothing replaced it, so a short series with an obvious
    # spike produced no finding.
    values = _noise(points, seed=3)
    values[points // 2] = 95.0

    payload = _validate(values)

    assert "anomaly_zscore" in payload["executed_analyzers"]
    assert "pyod_outlier" not in payload["executed_analyzers"]
    assert payload["findings"]
    zscore = next(item for item in payload["analyzer_executions"] if item["router_analyzer_id"] == "anomaly_zscore")
    assert "PyOD Outlier needs at least 50 points" in zscore["execution_reason"]


@pytest.mark.parametrize("points", [40, 288])
def test_plain_noise_gets_no_extra_spike_detector(points: int) -> None:
    payload = _validate(_noise(points, seed=5))

    assert "anomaly_zscore" not in payload["executed_analyzers"]
    assert payload["findings"] == []


def test_a_small_wobble_on_the_last_point_is_not_treated_as_a_spike() -> None:
    values = _noise(288, seed=8)
    values[-1] += 6.0

    payload = _validate(values)

    assert "pyod_outlier" not in payload["executed_analyzers"]
    assert payload["findings"] == []


def test_each_analyzer_says_why_it_ran_or_did_not() -> None:
    # The Router Decisions panel and the Grafana plugin read run_reason instead of guessing: STUMPY
    # and Data Health run on every series, and catalog-only candidates (PyOD, ADTK) can never run.
    values = _noise(288, seed=11)
    values[-5] = 95.0

    payload = _validate(values)

    by_id = {item["router_analyzer_id"]: item for item in payload["analyzer_executions"]}
    assert by_id["stumpy"]["execution_status"] == "completed"
    assert by_id["stumpy"]["run_reason"] == "always_run"
    assert by_id["data_health"]["run_reason"] == "always_run"
    assert by_id["pyod"]["run_reason"] == "not_built_in"
    assert by_id["adtk"]["run_reason"] == "not_built_in"
    assert by_id["pyod_outlier"]["execution_status"] == "completed"
    assert payload["findings"]
    assert by_id["pyod_outlier"]["in_finding"] is True
    assert by_id["stumpy"]["in_finding"] is False
