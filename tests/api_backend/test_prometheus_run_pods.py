"""Per-pod series read through a Grafana data source (the plugin's default source).

The plugin sends every series' samples to /api/ingestion/prometheus-run. The analyzers read one
line per metric and service, so per-pod series sent as they are were interleaved into one jagged
line. They are now combined the way New Analysis combines them, or refused with a clear message.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.api import ingestion
from backend.app.autonomous import drilldown
from backend.app.api.ingestion import PreviewPipelineStore
from backend.app.main import create_app
from backend.app.services.pod_split import SeriesAlreadyRead, combine_series, series_from_samples
from intelligence.pipeline import SignalPipeline

BEGIN = datetime(2026, 7, 26, 10, tzinfo=timezone.utc)
PODS = ["search-svc-0", "search-svc-1", "search-svc-2", "search-svc-3"]
QUERY = 'request_latency_p95{service="search-svc"}'


def _value(pod: str, i: int) -> float:
    # search-svc-2 goes slow for the second half of the hour; the others stay near 90.
    return 1150.0 if pod == "search-svc-2" and i >= 30 else 90.0 + i % 3


def _payload(pods=PODS, labels=None, **extra) -> dict:
    samples = [
        {
            "timestamp": (BEGIN + timedelta(minutes=i)).isoformat(),
            "value": _value(pod, i),
            "metric_name": "request_latency_p95",
            "service": "search-svc",
            "labels": {"__name__": "request_latency_p95", "service": "search-svc", "pod": pod, **(labels(pod) if labels else {})},
            "series_id": pod,
        }
        for pod in pods
        for i in range(60)
    ]
    return {
        "provider": "prometheus",
        "datasource_uid": "prom",
        "service": "search-svc",
        "metric_name": "request_latency_p95",
        "promql": QUERY,
        "from": BEGIN.isoformat(),
        "to": (BEGIN + timedelta(hours=1)).isoformat(),
        "step_seconds": 60,
        "series_count": len(pods),
        "sample_count": len(samples),
        "samples": samples,
        **extra,
    }


class _Captured:
    frames: list = []


def _pipeline(config):
    # A bare SignalPipeline writes to the database in config.yaml.
    pipeline = SignalPipeline(config, store=PreviewPipelineStore())
    original = pipeline.run_dataframe

    def run_dataframe(frame, **kwargs):
        _Captured.frames.append(frame.copy())
        return original(frame, **kwargs)

    pipeline.run_dataframe = run_dataframe
    return pipeline


def _post(payload: dict):
    _Captured.frames = []
    app = create_app("sqlite+pysqlite:///:memory:")
    with patch.object(ingestion, "SignalPipeline", _pipeline), TestClient(app) as client:
        return client.post("/api/ingestion/prometheus-run", json=payload)


def test_per_pod_series_are_combined_into_one_line() -> None:
    res = _post(_payload(combine="auto"))

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["promql"] == f"avg by (service) ({QUERY})"
    assert body["combined"]["label"] == "pod"
    assert body["combined"]["count"] == 4
    assert body["combined"]["how"] == "avg"
    assert body["combined"]["original_query"] == QUERY
    assert body["combined"]["odd"]["value"] == "search-svc-2"
    # The analyzers got one value per minute - the average of the 4 pods - not 4 interleaved ones.
    frame = _Captured.frames[0]
    assert len(frame) == 60
    assert frame["timestamp"].is_unique
    late = frame.sort_values("timestamp")["value"].iloc[45]
    assert late == (1150.0 + 3 * (90.0 + 45 % 3)) / 4


def test_a_chosen_combine_overrides_the_metric_default() -> None:
    res = _post(_payload(combine="max"))

    assert res.status_code == 200, res.text
    assert res.json()["combined"]["how"] == "max"
    assert res.json()["promql"] == f"max by (service) ({QUERY})"
    assert _Captured.frames[0]["value"].max() == 1150.0


def test_per_pod_series_without_combine_are_refused_not_mixed() -> None:
    res = _post(_payload())

    assert res.status_code == 400
    assert "which differ by pod" in res.json()["detail"]
    assert res.json()["detail"].endswith(f"combine them: avg by (service) ({QUERY})")
    assert _Captured.frames == []


def test_series_that_differ_by_more_than_the_pod_are_not_combined() -> None:
    # Two status codes per pod: combining would mix the codes too. Not combined; the normalizer
    # refuses the overlapping lines as it did before.
    pods = [f"{pod}|{code}" for pod in PODS[:2] for code in ("200", "500")]
    payload = _payload(pods=pods, combine="auto")
    for sample in payload["samples"]:
        pod, code = sample["series_id"].split("|")
        sample["labels"] = {**sample["labels"], "pod": pod, "code": code}

    res = _post(payload)

    assert res.status_code == 400
    assert "not monotonic" in res.json()["detail"]
    assert len(_Captured.frames[0]) == len(payload["samples"])


def test_one_series_is_analyzed_as_before() -> None:
    res = _post(_payload(pods=PODS[:1], combine="auto"))

    assert res.status_code == 200, res.text
    assert res.json()["combined"] is None
    assert len(_Captured.frames[0]) == 60


def test_drill_down_reads_the_pods_already_sent() -> None:
    calls = []
    real = ingestion.drill_down_findings

    def spy(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    breakdowns = []
    real_store = drilldown._store

    def store(db, run_id, finding, breakdown):
        breakdowns.append(breakdown)
        return real_store(db, run_id, finding, breakdown)

    with patch.object(ingestion, "drill_down_findings", spy), patch("backend.app.autonomous.drilldown._store", store):
        res = _post(_payload(combine="auto"))

    assert res.status_code == 200, res.text
    assert len(calls) == 1
    assert isinstance(calls[0]["prometheus"], SeriesAlreadyRead)
    assert calls[0]["config"].labels == ["pod"]
    assert calls[0]["promql"] == f"avg by (service) ({QUERY})"
    # The change is put on the slow pod.
    assert breakdowns and breakdowns[0]["status"] == "ok", breakdowns


def test_series_already_read_returns_the_window_asked_for() -> None:
    series = series_from_samples(ingestion.PrometheusAnalysisRequest.model_validate(_payload()).samples)
    window = SeriesAlreadyRead(series).preview("ignored", BEGIN + timedelta(minutes=10), BEGIN + timedelta(minutes=19), "60s")

    assert sorted(item.labels["pod"] for item in window.series) == PODS
    assert all(len(item.samples) == 10 for item in window.series)


def test_combine_series_combines_per_timestamp() -> None:
    series = series_from_samples(ingestion.PrometheusAnalysisRequest.model_validate(_payload(pods=PODS[:2])).samples)

    summed = combine_series(series, "sum")

    assert len(summed) == 60
    assert summed[0].value == 2 * 90.0
