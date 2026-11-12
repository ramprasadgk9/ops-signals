from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "config" / "demo_samples"
SAMPLE_FILES = sorted(SAMPLES_DIR.glob("*.csv"))


def _validate(csv_bytes: bytes, provider: str, metric_name: str = "uploaded_metric") -> dict:
    app = create_app("sqlite+pysqlite:///:memory:")
    data = {"provider": provider, "analyzer_id": "all", "service": "", "metric_name": metric_name}
    with TestClient(app) as client:
        response = client.post(
            "/api/ingestion/csv-validate",
            data=data,
            files={"file": ("upload.csv", io.BytesIO(csv_bytes), "text/csv")},
        )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("provider", ["prometheus", "generic"])
@pytest.mark.parametrize("sample", SAMPLE_FILES, ids=lambda path: path.name)
def test_every_sample_file_uploads_with_the_default_and_generic_provider(sample: Path, provider: str) -> None:
    # The New Analysis form defaults to Prometheus CSV, whose files say "metric"; the sample files
    # say "metric_name" and used to fail with "CSV is missing required columns: ['metric']".
    payload = _validate(sample.read_bytes(), provider)

    assert payload["sample_count"] > 0


def test_a_file_without_a_metric_column_takes_the_metric_typed_at_upload() -> None:
    csv_bytes = b"timestamp,value\n" + b"\n".join(
        f"2026-01-01T{hour:02d}:{minute:02d}:00Z,{40 + minute / 10}".encode() for hour in range(4) for minute in range(0, 60, 5)
    )

    payload = _validate(csv_bytes, "prometheus", metric_name="queue_depth")

    assert payload["sample_count"] > 0
    assert payload["metric_name"] == "queue_depth"
