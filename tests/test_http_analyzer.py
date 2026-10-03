"""HTTP-backed analyzers: Ops Signals posts each metric window to a service and turns its reply
into signals. A local HTTP server stands in for the service, so no real model is needed."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator

import pandas as pd
import pytest

from intelligence.analyzer_registry import (
    AnalyzerRegistration,
    HttpAnalyzerSpec,
    RouterSpec,
    instantiate,
    load_registrations,
)
from intelligence.analyzers.http_analyzer import HttpAnalyzer, HttpAnalyzerError


class _FakeService:
    """Records each request and answers with whatever the test sets."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.status = 200
        self.body: Any = {"findings": []}
        self.raw_body: bytes | None = None
        self.delay_seconds = 0.0
        service = self

        class Handler(BaseHTTPRequestHandler):
            def _reply(self) -> None:
                if service.delay_seconds:
                    threading.Event().wait(service.delay_seconds)
                payload = service.raw_body if service.raw_body is not None else json.dumps(service.body).encode()
                self.send_response(service.status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                service.requests.append(
                    {
                        "path": self.path,
                        "headers": dict(self.headers),
                        "json": json.loads(self.rfile.read(length) or b"{}"),
                    }
                )
                self._reply()

            def do_GET(self) -> None:  # noqa: N802
                service.requests.append({"path": self.path, "headers": dict(self.headers), "json": None})
                self._reply()

            def log_message(self, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    closed = False

    def close(self) -> None:
        self.closed = True
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def service() -> Iterator[_FakeService]:
    fake = _FakeService()
    yield fake
    if not fake.closed:
        fake.close()


def _frame(metric: str = "http_latency_ms", service_name: str = "checkout", periods: int = 6) -> pd.DataFrame:
    timestamps = pd.date_range("2026-10-01T00:00:00Z", periods=periods, freq="5min")
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "value": [100.0, 101.0, float("nan"), 99.0, 400.0, 102.0][:periods],
            "metric_name": metric,
            "service": service_name,
            "env": "prod",
        }
    )


def _analyzer(url: str, **kwargs: Any) -> HttpAnalyzer:
    return HttpAnalyzer(analyzer_id="remote_model", spec=HttpAnalyzerSpec(analyze_url=f"{url}/analyze", **kwargs))


def test_posts_each_series_as_timestamps_and_values(service: _FakeService) -> None:
    analyzer = HttpAnalyzer(
        analyzer_id="remote_model",
        spec=HttpAnalyzerSpec(analyze_url=f"{service.url}/analyze"),
        params={"threshold": 3, "external_runtime": {"type": "external_http", "analyze_url": "x"}},
    )

    analyzer.analyze(_frame())

    assert len(service.requests) == 1
    request = service.requests[0]
    assert request["path"] == "/analyze"
    body = request["json"]
    assert body["contract_version"] == 1
    assert body["analyzer_id"] == "remote_model"
    assert body["params"] == {"threshold": 3}
    [series] = body["series"]
    assert series["series_id"] == "0"
    assert series["metric_name"] == "http_latency_ms"
    assert series["service"] == "checkout"
    assert series["env"] == "prod"
    assert series["timestamps"][0] == "2026-10-01T00:00:00Z"
    assert series["values"] == [100.0, 101.0, None, 99.0, 400.0, 102.0]


def test_turns_findings_into_signals_with_defaults(service: _FakeService) -> None:
    service.body = {
        "findings": [
            {
                "start_time": "2026-10-01T00:20:00Z",
                "summary": "Latency spike to 400 ms.",
                "evidence": {"max_abs_zscore": 5.2, "model": "toto-22m"},
            }
        ]
    }

    [signal] = _analyzer(service.url).analyze(_frame())

    assert signal.analyzer_id == "remote_model"
    assert signal.signal_type == "anomaly"
    assert signal.severity == "medium"
    assert signal.confidence == 0.5
    assert signal.metric_name == "http_latency_ms"
    assert signal.service == "checkout"
    assert signal.env == "prod"
    assert signal.start_time == pd.Timestamp("2026-10-01T00:20:00Z").to_pydatetime()
    assert signal.end_time == signal.start_time
    assert signal.summary == "Latency spike to 400 ms."
    assert signal.evidence["max_abs_zscore"] == 5.2
    assert signal.evidence["model"] == "toto-22m"
    assert signal.evidence["library"] == "http"
    assert signal.evidence["remote_analyzer_url"] == f"{service.url}/analyze"


def test_matches_findings_to_series_by_series_id(service: _FakeService) -> None:
    frame = pd.concat([_frame("cpu", "api"), _frame("memory", "api")], ignore_index=True)
    service.body = {
        "findings": [
            {
                "series_id": "1",
                "signal_type": "baseline_shift",
                "severity": "high",
                "confidence": 1.7,
                "start_time": "2026-10-01T00:10:00Z",
                "end_time": "2026-10-01T00:25:00Z",
                "summary": "Memory moved to a new level.",
            }
        ]
    }

    [signal] = _analyzer(service.url).analyze(frame)

    assert [s["metric_name"] for s in service.requests[0]["json"]["series"]] == ["cpu", "memory"]
    assert signal.metric_name == "memory"
    assert signal.signal_type == "baseline_shift"
    assert signal.severity == "high"
    assert signal.confidence == 1.0
    assert signal.end_time == pd.Timestamp("2026-10-01T00:25:00Z").to_pydatetime()


def test_sends_the_api_key_from_an_environment_variable(service: _FakeService, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMOTE_MODEL_KEY", "secret-123")

    _analyzer(service.url, api_key_env="REMOTE_MODEL_KEY").analyze(_frame())

    assert service.requests[0]["headers"]["Authorization"] == "Bearer secret-123"


def test_empty_data_makes_no_call(service: _FakeService) -> None:
    assert _analyzer(service.url).analyze(_frame().iloc[0:0]) == []
    assert service.requests == []


def test_http_error_names_the_status_and_the_service_message(service: _FakeService) -> None:
    service.status = 500
    service.body = {"error": "model not loaded"}

    with pytest.raises(HttpAnalyzerError, match="HTTP 500.*model not loaded"):
        _analyzer(service.url).analyze(_frame())


def test_unreachable_service_names_the_url() -> None:
    analyzer = HttpAnalyzer(analyzer_id="remote_model", spec=HttpAnalyzerSpec(analyze_url="http://127.0.0.1:9/analyze", timeout_seconds=2))

    with pytest.raises(HttpAnalyzerError, match="127.0.0.1:9"):
        analyzer.analyze(_frame())


def test_slow_service_times_out(service: _FakeService) -> None:
    service.delay_seconds = 1.5

    with pytest.raises(HttpAnalyzerError, match="timed out"):
        _analyzer(service.url, timeout_seconds=0.3).analyze(_frame())


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (b"not json", "invalid JSON"),
        (json.dumps({"results": []}).encode(), "findings"),
        (json.dumps({"findings": [{"summary": "no time"}]}).encode(), r"finding 0.*start_time"),
        (json.dumps({"findings": [{"start_time": "2026-10-01T00:00:00Z", "summary": "x", "severity": "urgent"}]}).encode(), "severity"),
        (json.dumps({"findings": [{"start_time": "2026-10-01T00:00:00Z", "summary": "x", "signal_type": "magic"}]}).encode(), "signal_type"),
        (json.dumps({"findings": [{"start_time": "2026-10-01T00:00:00Z", "summary": "x", "series_id": "7"}]}).encode(), "series_id"),
    ],
)
def test_bad_replies_fail_with_a_clear_message(service: _FakeService, reply: bytes, message: str) -> None:
    service.raw_body = reply

    with pytest.raises(HttpAnalyzerError, match=message):
        _analyzer(service.url).analyze(_frame())


def test_series_id_is_required_when_several_series_are_sent(service: _FakeService) -> None:
    service.body = {"findings": [{"start_time": "2026-10-01T00:00:00Z", "summary": "x"}]}
    frame = pd.concat([_frame("cpu"), _frame("memory")], ignore_index=True)

    with pytest.raises(HttpAnalyzerError, match="series_id"):
        _analyzer(service.url).analyze(frame)


def test_health_check(service: _FakeService) -> None:
    healthy = _analyzer(service.url, health_check_url=f"{service.url}/health")
    assert healthy.check_health() is None
    assert service.requests[-1]["path"] == "/health"

    service.status = 503
    assert "HTTP 503" in (healthy.check_health() or "")

    assert _analyzer(service.url).check_health() is None


def test_instantiate_builds_an_http_analyzer_without_calling_it() -> None:
    registration = AnalyzerRegistration(
        analyzer_id="remote_model",
        display_name="Remote Model",
        enabled=True,
        source_file="test.yml",
        class_path=None,
        http=HttpAnalyzerSpec(analyze_url="http://127.0.0.1:9/analyze"),
        router=RouterSpec(),
        runtime_params={"threshold": 3},
    )

    analyzer = instantiate(registration, overrides={"threshold": 4})

    assert isinstance(analyzer, HttpAnalyzer)
    assert analyzer.analyzer_id == "remote_model"
    assert analyzer.params == {"threshold": 4}
    assert analyzer.capability().analyzer_id == "remote_model"


def test_registry_reads_api_key_env_and_rejects_non_http_urls(tmp_path) -> None:
    registry_dir = tmp_path / "analyzer_registry.d"
    registry_dir.mkdir()
    (registry_dir / "remote.yml").write_text(
        """
analyzers:
  remote_model:
    http:
      analyze_url: https://models.internal/analyze
      api_key_env: REMOTE_MODEL_KEY
  file_model:
    http:
      analyze_url: file:///etc/passwd
""".strip(),
        encoding="utf-8",
    )

    [registration] = load_registrations(registry_dir)

    assert registration.analyzer_id == "remote_model"
    assert registration.http is not None
    assert registration.http.api_key_env == "REMOTE_MODEL_KEY"


def test_pipeline_runs_a_registered_http_analyzer_and_survives_it_going_down(
    service: _FakeService, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil
    from pathlib import Path

    import yaml

    from intelligence import analyzer_selection
    from intelligence.config import load_config
    from intelligence.pipeline import SignalPipeline

    project_root = Path(__file__).resolve().parents[1]
    registry_dir = tmp_path / "config" / "analyzer_registry.d"
    registry_dir.mkdir(parents=True)
    shutil.copy(project_root / "config" / "analyzer_registry.d" / "builtin.yml", registry_dir / "builtin.yml")
    (registry_dir / "custom_remote_model.yml").write_text(
        yaml.safe_dump({"analyzers": {"remote_model": {"http": {"analyze_url": f"{service.url}/analyze"}}}})
    )
    monkeypatch.setattr(analyzer_selection, "_REPO_ROOT", tmp_path)
    config = load_config(project_root / "config.yaml")
    config.analysis.selection_mode = "all"

    class NullStore:
        engine = None

    pipeline = SignalPipeline(config=config, store=NullStore())
    analyzers = {a.analyzer_id: a for a in pipeline._build_analyzers([])}
    assert isinstance(analyzers["remote_model"], HttpAnalyzer)

    timestamps = pd.date_range("2026-10-01T00:00:00Z", periods=60, freq="5min")
    values = [100.0 + (i % 3) for i in range(60)]
    values[50] = 900.0
    frame = pd.DataFrame({"timestamp": timestamps, "value": values, "metric_name": "latency", "service": "api", "env": "prod"})
    chosen = [analyzers["remote_model"], analyzers["anomaly_zscore"]]
    service.body = {"findings": [{"start_time": "2026-10-01T04:10:00Z", "summary": "Spike.", "severity": "high"}]}

    signals, failed = pipeline._run_analyzers(chosen, frame, "run-1")

    assert failed == {}
    assert {s.analyzer_id for s in signals} == {"remote_model", "anomaly_zscore"}

    service.close()
    signals, failed = pipeline._run_analyzers(chosen, frame, "run-2")

    assert "remote_model" in failed
    assert "Could not reach" in failed["remote_model"]
    assert {s.analyzer_id for s in signals} == {"anomaly_zscore"}


def test_the_documented_example_service_works_with_the_adapter() -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "examples" / "http_analyzer" / "service.py"
    spec = importlib.util.spec_from_file_location("example_http_analyzer_service", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    server = ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        analyzer = _analyzer(url, health_check_url=f"{url}/health")
        timestamps = pd.date_range("2026-10-01T00:00:00Z", periods=60, freq="5min")
        values = [100.0 + (i % 5) for i in range(60)]
        values[40] = 400.0
        frame = pd.DataFrame({"timestamp": timestamps, "value": values, "metric_name": "latency", "service": "api", "env": "prod"})

        assert analyzer.check_health() is None
        [signal] = analyzer.analyze(frame)
    finally:
        server.shutdown()
        server.server_close()

    assert signal.start_time == timestamps[40].to_pydatetime()
    assert signal.severity == "high"
    assert "400" in signal.summary
