from __future__ import annotations

import io

from fastapi.testclient import TestClient

from backend.app.main import create_app


def _custom_csv_bytes() -> bytes:
    rows = ["event_time,measurement,metric"]
    rows.extend(f"2026-01-01T00:{minute:02d}:00Z,{40 + minute},cpu_usage" for minute in range(35))
    return "\n".join(rows).encode("utf-8")


def test_csv_validate_accepts_a_custom_column_mapping_typed_in_at_upload_time() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")

    with TestClient(app) as client:
        response = client.post(
            "/api/ingestion/csv-validate",
            data={
                "provider": "custom",
                "analyzer_id": "all",
                "service": "internal-tool",
                "metric_name": "cpu_usage",
                "interval": "5m",
                "custom_timestamp_column": "event_time",
                "custom_value_column": "measurement",
                "custom_metric_name_column": "metric",
            },
            files={"file": ("custom.csv", io.BytesIO(_custom_csv_bytes()), "text/csv")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "custom"
    assert payload["sample_count"] > 0
    assert payload["normalized_preview"][0]["metric_name"] == "cpu_usage"


def test_csv_validate_rejects_custom_provider_with_a_missing_column_name() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")

    with TestClient(app) as client:
        response = client.post(
            "/api/ingestion/csv-validate",
            data={
                "provider": "custom",
                "analyzer_id": "all",
                "service": "internal-tool",
                "metric_name": "cpu_usage",
                "interval": "5m",
                "custom_timestamp_column": "event_time",
                "custom_value_column": "measurement",
                # custom_metric_name_column intentionally omitted
            },
            files={"file": ("custom.csv", io.BytesIO(_custom_csv_bytes()), "text/csv")},
        )

    assert response.status_code == 400
    assert "metric_name" in response.json()["detail"]


def test_csv_validate_rejects_custom_provider_with_no_column_names_at_all() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")

    with TestClient(app) as client:
        response = client.post(
            "/api/ingestion/csv-validate",
            data={"provider": "custom", "analyzer_id": "all", "service": "svc", "metric_name": "m", "interval": "5m"},
            files={"file": ("custom.csv", io.BytesIO(_custom_csv_bytes()), "text/csv")},
        )

    assert response.status_code == 400


def test_custom_column_mapping_is_not_remembered_between_uploads() -> None:
    # Proves the "not persisted" claim: a second upload from a *different* custom layout, with no
    # mapping fields sent at all, must fail on its own terms rather than silently reusing the
    # first request's mapping.
    app = create_app("sqlite+pysqlite:///:memory:")

    with TestClient(app) as client:
        first = client.post(
            "/api/ingestion/csv-validate",
            data={
                "provider": "custom",
                "analyzer_id": "all",
                "service": "svc",
                "metric_name": "cpu_usage",
                "interval": "5m",
                "custom_timestamp_column": "event_time",
                "custom_value_column": "measurement",
                "custom_metric_name_column": "metric",
            },
            files={"file": ("custom.csv", io.BytesIO(_custom_csv_bytes()), "text/csv")},
        )
        assert first.status_code == 200

        second = client.post(
            "/api/ingestion/csv-validate",
            data={"provider": "custom", "analyzer_id": "all", "service": "svc", "metric_name": "cpu_usage", "interval": "5m"},
            files={"file": ("custom.csv", io.BytesIO(_custom_csv_bytes()), "text/csv")},
        )

    assert second.status_code == 400


def test_generic_provider_still_works_unaffected_by_the_custom_provider_addition() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    rows = ["timestamp,metric_name,value"]
    rows.extend(f"2026-01-01T00:{minute:02d}:00Z,cpu_usage,{40 + minute}" for minute in range(35))
    csv_bytes = "\n".join(rows).encode("utf-8")

    with TestClient(app) as client:
        response = client.post(
            "/api/ingestion/csv-validate",
            data={"provider": "generic", "analyzer_id": "all", "service": "svc", "metric_name": "cpu_usage", "interval": "5m"},
            files={"file": ("dataset.csv", io.BytesIO(csv_bytes), "text/csv")},
        )

    assert response.status_code == 200
    assert response.json()["sample_count"] > 0
