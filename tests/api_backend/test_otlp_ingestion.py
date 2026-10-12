"""Integration tests for the OTLP push receiver (POST /api/otlp/v1/metrics), the self-observability
endpoint (GET /api/metrics), and one pass of the scheduler's OTLP backlog analysis cycle. See
docs/design/otlp-metrics-ingestion-plan.md for the design this implements."""

from __future__ import annotations

import gzip
import time
from unittest.mock import patch

from fastapi.testclient import TestClient
from google.protobuf import json_format
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue

from datetime import datetime, timedelta, timezone

from backend.app.autonomous.scheduler import _infer_interval, _run_pending_otlp_analysis_once
from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import OtlpPendingPointEntity
from backend.app.otlp.limits import CardinalityTracker, RateLimiter


def _sample_request(*, service: str = "payments-api", point_count: int = 1) -> ExportMetricsServiceRequest:
    request = ExportMetricsServiceRequest()
    rm = request.resource_metrics.add()
    rm.resource.attributes.append(KeyValue(key="service.name", value=AnyValue(string_value=service)))
    scope_metrics = rm.scope_metrics.add()
    metric = scope_metrics.metrics.add()
    metric.name = "cpu_usage"
    now_ns = int(time.time() * 1e9)
    for i in range(point_count):
        point = metric.gauge.data_points.add()
        point.time_unix_nano = now_ns - (point_count - i) * 60_000_000_000
        point.as_double = 70.0 + i
    return request


def test_status_endpoint_reflects_traffic_the_settings_page_card_reads() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        # points_received_total is a lifetime Counter shared across this whole test process
        # (correct semantics for a Counter - it should never reset), so this checks the delta
        # rather than an absolute value, which would be order-dependent against other tests in
        # this file. backlog_size is genuinely per-test-isolated (computed live from this test's
        # own fresh in-memory DB), so an absolute-zero check on a fresh app is safe.
        before = client.get("/api/otlp/status").json()
        assert before["endpoint_path"] == "/api/otlp/v1/metrics"
        assert before["backlog_size"] == 0
        received_before = before["points_received_total"]

        request = _sample_request(point_count=4)
        client.post(
            "/api/otlp/v1/metrics",
            content=request.SerializeToString(),
            headers={"Content-Type": "application/x-protobuf"},
        )

        after = client.get("/api/otlp/status").json()
        assert after["points_received_total"] - received_before == 4
        assert after["backlog_size"] == 4


def test_protobuf_export_is_accepted_and_stored() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        # otlp_points_received_total is a lifetime Counter shared across the whole test process
        # (correct real-world semantics for a Counter - it should never reset), so this asserts
        # the delta from this POST rather than an absolute value, which would be order-dependent
        # against other tests in this file. otlp_backlog_size is genuinely per-test-isolated
        # (computed live from this test's own fresh in-memory DB), so that one is an exact check.
        received_before = client.get("/api/otlp/status").json()["points_received_total"]

        request = _sample_request(point_count=3)
        response = client.post(
            "/api/otlp/v1/metrics",
            content=request.SerializeToString(),
            headers={"Content-Type": "application/x-protobuf"},
        )
        assert response.status_code == 200
        assert response.content == b""  # empty ExportMetricsServiceResponse: no rejections

        status = client.get("/api/otlp/status").json()
        assert status["points_received_total"] - received_before == 3
        assert status["backlog_size"] == 3

    session_local = get_session_local()
    with session_local() as db:
        rows = db.query(OtlpPendingPointEntity).all()
        assert len(rows) == 3
        assert {row.service for row in rows} == {"payments-api"}
        assert {row.metric_name for row in rows} == {"cpu_usage"}


def test_json_export_is_accepted_and_stored() -> None:
    from google.protobuf import json_format

    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        request = _sample_request(point_count=1)
        response = client.post(
            "/api/otlp/v1/metrics",
            content=json_format.MessageToJson(request),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200

    session_local = get_session_local()
    with session_local() as db:
        assert db.query(OtlpPendingPointEntity).count() == 1


def test_malformed_body_is_rejected_with_400() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        response = client.post(
            "/api/otlp/v1/metrics",
            content=b"not a valid protobuf payload",
            headers={"Content-Type": "application/x-protobuf"},
        )
        assert response.status_code == 400


def test_gzip_body_is_decompressed_like_an_otel_collector_sends_it() -> None:
    # The Collector's otlphttp exporter gzips by default; before this, every batch got a 400.
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        response = client.post(
            "/api/otlp/v1/metrics",
            content=gzip.compress(_sample_request(service="gzip-api", point_count=3).SerializeToString()),
            headers={"Content-Type": "application/x-protobuf", "Content-Encoding": "gzip"},
        )
        assert response.status_code == 200
        with get_session_local()() as db:
            assert db.query(OtlpPendingPointEntity).filter(OtlpPendingPointEntity.service == "gzip-api").count() == 3


def test_gzip_json_body_is_decompressed_too() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        body = json_format.MessageToJson(_sample_request(service="gzip-json-api")).encode()
        response = client.post(
            "/api/otlp/v1/metrics",
            content=gzip.compress(body),
            headers={"Content-Type": "application/json", "Content-Encoding": "GZIP"},
        )
        assert response.status_code == 200


def test_body_that_says_gzip_but_is_not_is_rejected_with_400() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        response = client.post(
            "/api/otlp/v1/metrics",
            content=_sample_request().SerializeToString(),
            headers={"Content-Type": "application/x-protobuf", "Content-Encoding": "gzip"},
        )
        assert response.status_code == 400
        assert "gzip" in response.text


def test_gzip_body_that_inflates_past_the_limit_is_rejected_with_413() -> None:
    # A small compressed body must not get around the size limit by inflating after the check.
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client, patch("backend.app.api.otlp.MAX_OTLP_BYTES", 1000):
        compressed = gzip.compress(b"\0" * 100_000)
        assert len(compressed) < 1000
        response = client.post(
            "/api/otlp/v1/metrics",
            content=compressed,
            headers={"Content-Type": "application/x-protobuf", "Content-Encoding": "gzip"},
        )
        assert response.status_code == 413


def test_an_unsupported_content_encoding_is_rejected_with_415() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        response = client.post(
            "/api/otlp/v1/metrics",
            content=b"anything",
            headers={"Content-Type": "application/x-protobuf", "Content-Encoding": "zstd"},
        )
        assert response.status_code == 415
        assert "gzip" in response.text


def test_oversized_body_is_rejected_with_413() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client, patch("backend.app.api.otlp.MAX_OTLP_BYTES", 10):
        response = client.post(
            "/api/otlp/v1/metrics",
            content=b"x" * 100,
            headers={"Content-Type": "application/x-protobuf"},
        )
        assert response.status_code == 413


def test_rate_limited_batch_is_rejected_with_429_and_stores_nothing() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with (
        TestClient(app) as client,
        patch("backend.app.api.otlp.rate_limiter", RateLimiter(limit_per_minute=2)),
    ):
        request = _sample_request(point_count=5)
        response = client.post(
            "/api/otlp/v1/metrics",
            content=request.SerializeToString(),
            headers={"Content-Type": "application/x-protobuf"},
        )
        assert response.status_code == 429
        assert "Retry-After" in response.headers

    session_local = get_session_local()
    with session_local() as db:
        assert db.query(OtlpPendingPointEntity).count() == 0


def test_cardinality_cap_reports_partial_success_and_stores_only_allowed_series() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with (
        TestClient(app) as client,
        patch("backend.app.api.otlp.cardinality_tracker", CardinalityTracker(max_series_per_metric=1)),
    ):
        request = ExportMetricsServiceRequest()
        rm = request.resource_metrics.add()
        scope_metrics = rm.scope_metrics.add()
        metric = scope_metrics.metrics.add()
        metric.name = "cpu_usage"
        now_ns = int(time.time() * 1e9)
        for host in ("host-1", "host-2"):
            point = metric.gauge.data_points.add()
            point.time_unix_nano = now_ns
            point.as_double = 1.0
            point.attributes.append(KeyValue(key="host.name", value=AnyValue(string_value=host)))

        response = client.post(
            "/api/otlp/v1/metrics",
            content=request.SerializeToString(),
            headers={"Content-Type": "application/x-protobuf"},
        )
        assert response.status_code == 200

        from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
            ExportMetricsServiceResponse,
        )

        parsed_response = ExportMetricsServiceResponse()
        parsed_response.ParseFromString(response.content)
        assert parsed_response.partial_success.rejected_data_points == 1

    session_local = get_session_local()
    with session_local() as db:
        assert db.query(OtlpPendingPointEntity).count() == 1


def _points_at(*, count: int, spacing: timedelta) -> list[OtlpPendingPointEntity]:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [OtlpPendingPointEntity(timestamp=base + spacing * i) for i in range(count)]


def test_infer_interval_matches_the_actual_gap_between_points() -> None:
    # A hardcoded interval smaller than the real gap (e.g. always "1m" for 5-minute-spaced data)
    # leaves normalize_timeseries()'s resample step filling most buckets with NaN, diluting the
    # signal analyzers see - this locks in the fix for that bug.
    assert _infer_interval(_points_at(count=10, spacing=timedelta(minutes=5))) == "5m"
    assert _infer_interval(_points_at(count=10, spacing=timedelta(seconds=15))) == "15s"
    assert _infer_interval(_points_at(count=10, spacing=timedelta(seconds=90))) == "1m"
    assert _infer_interval(_points_at(count=1, spacing=timedelta(minutes=5))) == "1m"  # no gap to infer from


def _interval_seconds(label: str) -> int:
    return int(label[:-1]) * (60 if label.endswith("m") else 1)


def test_infer_interval_is_not_fooled_by_two_overlapping_sends_for_the_same_group() -> None:
    # Regression test for a real production incident: two independent 5-minute-interval sends
    # for the same (service, metric_name) landed in the pending backlog before a cycle ran (e.g.
    # the same script invoked twice ~20s apart, or two pods of one service each exporting on
    # their own timer). Merged and sorted, consecutive gaps alternate between ~20s and ~280s - the
    # *previous* median-of-consecutive-gaps implementation locked onto the 20s gap, inferring an
    # interval far finer than either send's real cadence and upsampling a ~576-point series into
    # 4307 resample buckets, 87% of them NaN. This asserts the general property that actually
    # matters: the number of resample buckets the inferred interval implies must stay within a
    # small multiple of the real point count, however the batch is interleaved - not an exact
    # interval value, since "the right interval for two overlapping sends" has no single correct
    # answer, only bad and reasonable ones.
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    series_a = [base + timedelta(minutes=5) * i for i in range(288)]
    series_b = [base + timedelta(minutes=5) * i + timedelta(seconds=20) for i in range(288)]
    rows = [OtlpPendingPointEntity(timestamp=ts) for ts in [*series_a, *series_b]]

    interval = _infer_interval(rows)
    interval_seconds = _interval_seconds(interval)
    span_seconds = (max(row.timestamp for row in rows) - min(row.timestamp for row in rows)).total_seconds()
    implied_buckets = span_seconds / interval_seconds

    assert interval_seconds >= 60, f"collapsed to a near-instant interval ({interval}) despite 5-minute-spaced source data"
    assert implied_buckets <= 2 * len(rows), f"{implied_buckets} buckets for {len(rows)} points would still dilute the series with NaN"


def test_scheduler_cycle_analyzes_pending_points_and_clears_the_backlog() -> None:
    # MetricAnalysisExecutor builds its own PostgresStore when none is passed in - a real Postgres
    # connection, independent of the SQLAlchemy session this test's app otherwise runs on (see
    # tests/api_backend/conftest.py's `db_session` fixture, which points at sqlite+pysqlite). CI
    # has no Postgres for the backend test job by design (only sqlite - see .github/workflows/ci.yml's
    # comment), so calling it for real here would fail there exactly as it failed locally once a
    # real Postgres wasn't coincidentally already running. Patched out the same way
    # test_autonomous_policies.py's scheduler tests already mock execute_autonomous_plan_once -
    # this test's job is verifying the backlog is grouped and cleared, not re-verifying analyzer
    # execution (that's MetricAnalysisExecutor's own test coverage).
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        request = _sample_request(point_count=5)
        response = client.post(
            "/api/otlp/v1/metrics",
            content=request.SerializeToString(),
            headers={"Content-Type": "application/x-protobuf"},
        )
        assert response.status_code == 200

    session_local = get_session_local()
    with session_local() as db:
        assert db.query(OtlpPendingPointEntity).count() == 5

    with patch("backend.app.autonomous.scheduler.MetricAnalysisExecutor") as mock_executor_cls:
        _run_pending_otlp_analysis_once()

    assert mock_executor_cls.return_value.execute_dataframe.called
    with session_local() as db:
        assert db.query(OtlpPendingPointEntity).count() == 0
