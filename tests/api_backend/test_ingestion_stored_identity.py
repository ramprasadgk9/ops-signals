"""QA-14: a CSV run with service "qa-svc2" in the form reported "qa-svc2" while its findings were
stored under the file's own service column, "qa-svc". Prometheus runs echoed the request too."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd

from backend.app.api.ingestion import PreviewPipelineStore, _stored_identity
from intelligence.pipeline import SignalPipeline

SAMPLE_CSV = Path(__file__).resolve().parents[2] / "sample_data" / "cpu_usage_sample.csv"


def test_a_csv_run_reports_the_service_its_data_was_stored_under(client) -> None:
    # The real pipeline, with a store that writes nothing: its default store is config.yaml's Postgres.
    with patch("backend.app.api.ingestion.SignalPipeline", lambda config: SignalPipeline(config, store=PreviewPipelineStore())):
        response = client.post(
            "/api/ingestion/csv-run",
            data={"provider": "generic", "service": "qa-svc2", "metric_name": "cpu_usage", "interval": "auto"},
            files={"file": ("cpu.csv", SAMPLE_CSV.read_bytes(), "text/csv")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "checkout"
    assert any("service you entered (qa-svc2) only fills rows that have none" in warning for warning in body["warnings"])
    assert not any("metric name" in warning for warning in body["warnings"])


def test_the_entered_service_is_reported_when_the_data_has_none() -> None:
    normalized = pd.DataFrame({"metric_name": ["cpu_usage"], "value": [1.0], "service": [None]})

    assert _stored_identity(normalized, "qa-svc2", "cpu_usage") == ("qa-svc2", "cpu_usage", [])


def test_several_stored_services_are_all_named() -> None:
    normalized = pd.DataFrame({"metric_name": ["cpu_usage"] * 3, "value": [1.0, 2.0, 3.0], "service": ["cart", "auth", "cart"]})

    service, metric, warnings = _stored_identity(normalized, "cart", "cpu_usage")

    assert (service, metric, warnings) == ("auth, cart", "cpu_usage", [])
