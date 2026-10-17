"""QA-17: error responses passed pandas, codec and database driver messages straight through,
including the database host and port during an outage."""

from __future__ import annotations

import io
import logging
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app


@pytest.fixture()
def client():
    with TestClient(create_app("sqlite+pysqlite:///:memory:"), raise_server_exceptions=False) as test_client:
        yield test_client


def _validate(client, content: bytes):
    return client.post(
        "/api/ingestion/csv-validate",
        files={"file": ("upload.csv", io.BytesIO(content), "text/csv")},
        data={"provider": "generic", "analyzer_id": "all"},
    )


def test_a_header_only_csv_says_there_is_no_data(client) -> None:
    response = _validate(client, b"timestamp,metric_name,value\n")

    assert response.status_code == 400
    assert response.json()["detail"] == "The data has no rows to analyze: only a header, or nothing at all."


def test_an_empty_file_says_so(client) -> None:
    response = _validate(client, b"")

    assert response.status_code == 400
    assert response.json()["detail"] == "The CSV file is empty."


def test_a_binary_file_says_it_is_not_a_readable_csv(client) -> None:
    response = _validate(client, bytes(range(256)) * 4)

    assert response.status_code == 400
    assert response.json()["detail"] == "The file isn't a readable CSV: it should be plain UTF-8 text."


def test_an_unexpected_failure_hides_the_details_and_logs_them(client, caplog) -> None:
    secret = "connection to server at 10.0.0.12 port 5432 failed: password authentication failed"
    with patch("backend.app.api.ingestion.SignalPipeline") as pipeline_cls, caplog.at_level(logging.ERROR):
        pipeline_cls.return_value.run.side_effect = RuntimeError(secret)
        response = _validate(client, b"timestamp,metric_name,value\n2026-01-01T00:00:00Z,cpu,1\n")

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail.startswith("Validation failed. Details are in the server log (error ")
    assert "10.0.0.12" not in detail and "5432" not in detail
    error_id = detail.rsplit(" ", 1)[1].rstrip(").")
    assert any(error_id in record.getMessage() and secret in str(record.exc_info[1]) for record in caplog.records)
