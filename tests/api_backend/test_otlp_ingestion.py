"""Integration tests for the OTLP push receiver (POST /api/otlp/v1/metrics), the self-observability
endpoint (GET /api/metrics), and one pass of the scheduler's OTLP backlog analysis cycle. See
docs/design/otlp-metrics-ingestion-plan.md for the design this implements."""

from __future__ import annotations

import gzip
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from google.protobuf import json_format
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue

from datetime import datetime, timedelta, timezone

from backend.app.autonomous.scheduler import _infer_interval, _run_pending_otlp_analysis_once
from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import NormalizedPoint, OtlpPendingPointEntity
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


def test_an_unsupported_content_type_is_rejected_with_415() -> None:
    # QA-25: text/plain was parsed as protobuf and answered 400 "wire format corrupt".
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        response = client.post("/api/otlp/v1/metrics", content=b"cpu_usage 70", headers={"Content-Type": "text/plain"})
        assert response.status_code == 415
        assert "application/x-protobuf" in response.text

        # No Content-Type at all is still read as protobuf.
        untyped = client.post(
            "/api/otlp/v1/metrics", content=_sample_request().SerializeToString(), headers={"Content-Type": ""}
        )
        assert untyped.status_code == 200


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
        # Waited long enough to be due (see the tests below for when a series waits).
        _age_pending(db, minutes=11)

    with patch("backend.app.autonomous.scheduler.MetricAnalysisExecutor") as mock_executor_cls:
        _run_pending_otlp_analysis_once()

    assert mock_executor_cls.return_value.execute_dataframe.called
    with session_local() as db:
        assert db.query(OtlpPendingPointEntity).count() == 0


def _age_pending(db, *, minutes: int) -> None:
    received = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    db.query(OtlpPendingPointEntity).update({OtlpPendingPointEntity.received_at: received})
    db.commit()


def _pending(db, *, count: int, start: datetime, service: str = "payments-api", metric: str = "cpu_usage", per_timestamp: int = 1) -> None:
    for index in range(count):
        for state in range(per_timestamp):
            db.add(
                OtlpPendingPointEntity(
                    metric_name=metric,
                    metric_type="gauge",
                    timestamp=start + timedelta(seconds=15 * index),
                    value=float(index),
                    service=service,
                    attributes_json={"state": str(state)},
                    received_at=datetime.now(timezone.utc),
                )
            )
    db.commit()


def test_a_collector_s_few_fresh_points_wait_instead_of_being_analyzed_alone(db_session) -> None:
    # A Collector sends a few points per series every 15s. Analyzed alone, each batch is far
    # below the 30-80 points analyzers need, so every check was skipped and no finding could
    # ever appear from a live Collector.
    # db_session points the engine at a fresh in-memory database; create_app alone would not.
    session_local = get_session_local()
    with session_local() as db:
        _pending(db, count=6, start=datetime.now(timezone.utc) - timedelta(minutes=1))

    with patch("backend.app.autonomous.scheduler.MetricAnalysisExecutor") as mock_executor_cls:
        _run_pending_otlp_analysis_once()

    assert not mock_executor_cls.return_value.execute_dataframe.called
    with session_local() as db:
        assert db.query(OtlpPendingPointEntity).count() == 6


def test_a_metric_with_many_rows_per_timestamp_still_waits(db_session) -> None:
    # system.cpu.time sends one row per CPU state: 8 rows a scrape is not a backfill.
    # db_session points the engine at a fresh in-memory database; create_app alone would not.
    session_local = get_session_local()
    with session_local() as db:
        _pending(db, count=10, start=datetime.now(timezone.utc) - timedelta(minutes=3), per_timestamp=8)

    with patch("backend.app.autonomous.scheduler.MetricAnalysisExecutor") as mock_executor_cls:
        _run_pending_otlp_analysis_once()

    assert not mock_executor_cls.return_value.execute_dataframe.called


def test_each_due_series_is_analyzed_whole_within_the_cycle_budget(db_session) -> None:
    # A cycle that took the oldest N rows across all series analyzed each series on a slice of
    # its points; the budget now stops between series instead.
    # db_session points the engine at a fresh in-memory database; create_app alone would not.
    session_local = get_session_local()
    start = datetime.now(timezone.utc) - timedelta(minutes=12)
    with session_local() as db:
        _pending(db, count=40, start=start, service="a")
        _pending(db, count=40, start=start, service="b")
        _age_pending(db, minutes=11)

    with (
        patch("backend.app.autonomous.scheduler.MAX_BACKLOG_PER_CYCLE", 50),
        patch("backend.app.autonomous.scheduler.MetricAnalysisExecutor") as mock_executor_cls,
    ):
        _run_pending_otlp_analysis_once()

    calls = mock_executor_cls.return_value.execute_dataframe.call_args_list
    assert len(calls) == 1
    assert len(calls[0].args[0]) == 40
    with session_local() as db:
        assert db.query(OtlpPendingPointEntity).count() == 40


def test_a_large_batch_is_analyzed_at_once_as_a_backfill_needs(db_session) -> None:
    # db_session points the engine at a fresh in-memory database; create_app alone would not.
    session_local = get_session_local()
    with session_local() as db:
        _pending(db, count=288, start=datetime.now(timezone.utc) - timedelta(hours=24))

    with patch("backend.app.autonomous.scheduler.MetricAnalysisExecutor") as mock_executor_cls:
        _run_pending_otlp_analysis_once()

    assert mock_executor_cls.return_value.execute_dataframe.called


def test_a_due_series_is_analyzed_with_its_stored_history_which_is_not_stored_twice(db_session) -> None:
    # db_session points the engine at a fresh in-memory database; create_app alone would not.
    session_local = get_session_local()
    now = datetime.now(timezone.utc)
    new_from = now - timedelta(minutes=10)
    with session_local() as db:
        for index in range(100):
            db.add(
                NormalizedPoint(
                    source="otel",
                    metric_name="cpu_usage",
                    service="payments-api",
                    timestamp=new_from - timedelta(seconds=15 * (100 - index)),
                    value=1.0,
                )
            )
        # Other series, sources and old points are not this series' recent history.
        db.add(NormalizedPoint(source="otel", metric_name="cpu_usage", service="checkout", timestamp=new_from - timedelta(minutes=5), value=9.0))
        db.add(NormalizedPoint(source="prometheus", metric_name="cpu_usage", service="payments-api", timestamp=new_from - timedelta(minutes=5), value=9.0))
        db.add(NormalizedPoint(source="otel", metric_name="cpu_usage", service="payments-api", timestamp=now - timedelta(days=2), value=9.0))
        db.commit()
        _pending(db, count=40, start=new_from)
        _age_pending(db, minutes=11)

    with patch("backend.app.autonomous.scheduler.MetricAnalysisExecutor") as mock_executor_cls:
        _run_pending_otlp_analysis_once()

    call = mock_executor_cls.return_value.execute_dataframe.call_args
    frame = call.args[0]
    assert len(frame) == 140
    assert set(frame["value"].head(100)) == {1.0}
    assert call.kwargs["run_metadata"]["history_point_count"] == 100
    last_history = new_from - timedelta(seconds=15)
    assert call.kwargs["persist_points_after"] == last_history


def test_a_batch_whose_analysis_fails_is_dropped_so_it_cannot_block_the_rest(db_session) -> None:
    session_local = get_session_local()
    with session_local() as db:
        _pending(db, count=40, start=datetime.now(timezone.utc) - timedelta(minutes=12))
        _age_pending(db, minutes=11)

    with patch("backend.app.autonomous.scheduler.MetricAnalysisExecutor") as mock_executor_cls:
        mock_executor_cls.return_value.execute_dataframe.side_effect = ValueError("bad input")
        _run_pending_otlp_analysis_once()

    with session_local() as db:
        assert db.query(OtlpPendingPointEntity).count() == 0


def test_gaps_stored_in_the_history_are_left_out() -> None:
    # Stored points include NaN where a series had a gap. Read back as input they failed
    # normalization, so from the third round on every series' analysis failed.
    from backend.app.autonomous.scheduler import _otlp_history

    # Postgres stores NaN; SQLite can't, so the query is stubbed with what Postgres returns.
    new_from = datetime.now(timezone.utc)
    stored = [
        NormalizedPoint(source="otel", metric_name="m", service="s", timestamp=new_from - timedelta(minutes=3 - index), value=value)
        for index, value in enumerate([1.0, float("nan"), 3.0])
    ]

    class _Query:
        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def all(self):
            return stored

    class _Db:
        def query(self, *args):
            return _Query()

    history = _otlp_history(_Db(), "s", "m", before=new_from)

    assert [point["value"] for point in history] == [1.0, 3.0]


def test_executor_stores_only_the_points_after_the_history(monkeypatch) -> None:
    import pandas as pd

    from backend.app.autonomous.metric_executor import MetricAnalysisExecutor
    from intelligence.config import load_config

    saved: list[pd.DataFrame] = []

    class _Store:
        engine = None

        def save_normalized_points(self, frame, analysis_run_id=None):
            saved.append(frame)

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    config = load_config("config.yaml")
    executor = MetricAnalysisExecutor(config, store=_Store())
    monkeypatch.setattr(executor, "_route_analyzers", lambda frame: ([], {}, "test"))
    monkeypatch.setattr(executor, "_build_analyzers", lambda routing: [])
    monkeypatch.setattr(executor, "_evaluate_behavior_intelligence", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_counts", lambda *args, **kwargs: (0, 0, 0))
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    normalized = pd.DataFrame(
        {"timestamp": [start + timedelta(minutes=i) for i in range(10)], "metric_name": "cpu_usage", "service": "svc", "value": 1.0}
    )

    executor.execute_normalized(normalized, db=object(), persist_points_after=start + timedelta(minutes=5))

    assert len(saved) == 1
    assert list(saved[0]["timestamp"]) == [start + timedelta(minutes=i) for i in range(6, 10)]


def test_a_running_total_counter_is_stored_as_its_rate() -> None:
    from opentelemetry.proto.metrics.v1.metrics_pb2 import AggregationTemporality

    start_ns = int(time.time() * 1e9) - 600_000_000_000

    def export(seconds: int, total: float) -> bytes:
        request = ExportMetricsServiceRequest()
        rm = request.resource_metrics.add()
        rm.resource.attributes.append(KeyValue(key="service.name", value=AnyValue(string_value="rates-test")))
        metric = rm.scope_metrics.add().metrics.add()
        metric.name = "container.cpu.usage.total"
        metric.sum.is_monotonic = True
        metric.sum.aggregation_temporality = AggregationTemporality.AGGREGATION_TEMPORALITY_CUMULATIVE
        metric.sum.data_points.add(time_unix_nano=start_ns + seconds * 1_000_000_000, start_time_unix_nano=start_ns, as_double=total)
        return request.SerializeToString()

    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        for seconds, total in ((15, 1000.0), (30, 1300.0)):
            response = client.post("/api/otlp/v1/metrics", content=export(seconds, total), headers={"Content-Type": "application/x-protobuf"})
            assert response.status_code == 200

    with get_session_local()() as db:
        stored = db.query(OtlpPendingPointEntity).filter(OtlpPendingPointEntity.service == "rates-test").all()
    assert [row.value for row in stored] == [20.0]


def _postgres_engine(*, lock_free: bool) -> tuple[MagicMock, list[str]]:
    """A stand-in Postgres engine whose advisory lock is free or held by another backend."""
    statements: list[str] = []
    conn = MagicMock()

    def execute(statement, params=None):
        statements.append(str(statement))
        result = MagicMock()
        result.scalar.return_value = lock_free
        return result

    conn.execute.side_effect = execute
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    engine.connect.return_value.__enter__.return_value = conn
    return engine, statements


def test_otlp_cycle_is_skipped_while_another_backend_holds_the_lock() -> None:
    engine, statements = _postgres_engine(lock_free=False)
    with (
        patch("backend.app.autonomous.scheduler.get_engine", return_value=engine),
        patch("backend.app.autonomous.scheduler._analyze_pending_otlp") as analyze,
    ):
        _run_pending_otlp_analysis_once()

    analyze.assert_not_called()
    assert statements == ["SELECT pg_try_advisory_lock(:key)"]


def test_otlp_cycle_runs_and_releases_the_lock() -> None:
    engine, statements = _postgres_engine(lock_free=True)
    with (
        patch("backend.app.autonomous.scheduler.get_engine", return_value=engine),
        patch("backend.app.autonomous.scheduler._analyze_pending_otlp") as analyze,
    ):
        _run_pending_otlp_analysis_once()

    analyze.assert_called_once()
    assert statements == ["SELECT pg_try_advisory_lock(:key)", "SELECT pg_advisory_unlock(:key)"]


def test_otlp_lock_is_released_when_the_cycle_fails() -> None:
    engine, statements = _postgres_engine(lock_free=True)
    with (
        patch("backend.app.autonomous.scheduler.get_engine", return_value=engine),
        patch("backend.app.autonomous.scheduler._analyze_pending_otlp", side_effect=RuntimeError("synthetic failure")),
        pytest.raises(RuntimeError),
    ):
        _run_pending_otlp_analysis_once()

    assert statements[-1] == "SELECT pg_advisory_unlock(:key)"
