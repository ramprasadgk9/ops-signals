from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from backend.app.api import ingestion as ingestion_module
from backend.app.main import create_app


def _small_csv_bytes() -> bytes:
    rows = ["timestamp,metric_name,value"]
    rows.extend(f"2026-01-01T00:{minute:02d}:00Z,cpu_usage,{40 + minute}" for minute in range(10))
    return "\n".join(rows).encode("utf-8")


@pytest.fixture
def small_upload_limit(monkeypatch: pytest.MonkeyPatch) -> int:
    limit = 200  # bytes - deliberately tiny so the test doesn't need to generate a huge payload
    monkeypatch.setattr(ingestion_module, "MAX_UPLOAD_BYTES", limit)
    return limit


def test_csv_validate_rejects_an_upload_over_the_configured_byte_limit(small_upload_limit: int) -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    oversized = b"x" * (small_upload_limit + 1)

    with TestClient(app) as client:
        response = client.post(
            "/api/ingestion/csv-validate",
            data={"provider": "generic", "analyzer_id": "all", "service": "svc", "metric_name": "m", "interval": "5m"},
            files={"file": ("dataset.csv", io.BytesIO(oversized), "text/csv")},
        )

    assert response.status_code == 413
    assert str(small_upload_limit) in response.json()["detail"]


def test_csv_run_rejects_an_upload_over_the_configured_byte_limit(small_upload_limit: int) -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    oversized = b"x" * (small_upload_limit + 1)

    with TestClient(app) as client:
        response = client.post(
            "/api/ingestion/csv-run",
            data={"provider": "generic", "service": "svc", "metric_name": "m", "interval": "5m"},
            files={"file": ("dataset.csv", io.BytesIO(oversized), "text/csv")},
        )

    assert response.status_code == 413


def test_csv_validate_leaves_no_temp_file_behind_for_a_rejected_upload(small_upload_limit: int, tmp_path) -> None:
    from backend.app.services.timeseries_routing_service import repo_root

    upload_dir = repo_root() / ".tmp_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    before = set(upload_dir.iterdir())

    app = create_app("sqlite+pysqlite:///:memory:")
    oversized = b"x" * (small_upload_limit + 1)
    with TestClient(app) as client:
        client.post(
            "/api/ingestion/csv-validate",
            data={"provider": "generic", "analyzer_id": "all", "service": "svc", "metric_name": "m", "interval": "5m"},
            files={"file": ("dataset.csv", io.BytesIO(oversized), "text/csv")},
        )

    after = set(upload_dir.iterdir())
    assert after == before


def test_csv_validate_still_accepts_an_upload_within_the_limit() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")

    with TestClient(app) as client:
        response = client.post(
            "/api/ingestion/csv-validate",
            data={"provider": "generic", "analyzer_id": "all", "service": "svc", "metric_name": "cpu_usage", "interval": "5m"},
            files={"file": ("dataset.csv", io.BytesIO(_small_csv_bytes()), "text/csv")},
        )

    assert response.status_code == 200
