from __future__ import annotations

import io
import random
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.app.main import create_app


def _step_change_csv(*, minutes_between_points: int, points: int = 288) -> bytes:
    """A clean series with no gaps that steps from about 50 to about 80 halfway through."""
    rng = random.Random(7)
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    rows = ["timestamp,metric_name,value"]
    for index in range(points):
        level = 50.0 if index < points // 2 else 80.0
        timestamp = start + timedelta(minutes=minutes_between_points * index)
        rows.append(f"{timestamp.strftime('%Y-%m-%dT%H:%M:%SZ')},cpu_usage,{level + rng.gauss(0, 1.5):.3f}")
    return "\n".join(rows).encode("utf-8")


def _validate(csv_bytes: bytes, **form: str) -> dict:
    app = create_app("sqlite+pysqlite:///:memory:")
    data = {"provider": "generic", "analyzer_id": "all", "service": "checkout", "metric_name": "cpu_usage", **form}
    with TestClient(app) as client:
        response = client.post(
            "/api/ingestion/csv-validate",
            data=data,
            files={"file": ("upload.csv", io.BytesIO(csv_bytes), "text/csv")},
        )
    assert response.status_code == 200, response.text
    return response.json()


def test_a_15_minute_csv_uploaded_with_default_settings_finds_the_baseline_shift() -> None:
    # QA-01: the form used to send 5m, which turned each 15-minute point into one real bucket and
    # two empty ones; every analyzer was rejected for missing values and nothing was found.
    payload = _validate(_step_change_csv(minutes_between_points=15))

    assert payload["requested_interval"] == "auto"
    assert payload["interval"] == "15m"
    assert payload["sample_count"] == 288
    assert payload["warnings"] == []
    assert "ruptures" in payload["executed_analyzers"]
    assert any("baseline shift" in finding["title"] for finding in payload["findings"])


def test_5_minute_data_gives_the_same_result_with_auto_as_with_an_explicit_5m() -> None:
    csv_bytes = _step_change_csv(minutes_between_points=5)

    auto = _validate(csv_bytes)
    explicit = _validate(csv_bytes, interval="5m")

    assert auto["interval"] == explicit["interval"] == "5m"
    assert auto["sample_count"] == explicit["sample_count"] == 288
    assert auto["executed_analyzers"] == explicit["executed_analyzers"]
    assert [finding["title"] for finding in auto["findings"]] == [finding["title"] for finding in explicit["findings"]]


def test_an_explicit_interval_finer_than_the_data_is_kept_and_explained() -> None:
    payload = _validate(_step_change_csv(minutes_between_points=15), interval="5m")

    assert payload["requested_interval"] == "5m"
    assert payload["interval"] == "5m"
    assert payload["sample_count"] > 288
    assert len(payload["warnings"]) == 1
    assert "every 15m" in payload["warnings"][0]
    assert "67%" in payload["warnings"][0]
