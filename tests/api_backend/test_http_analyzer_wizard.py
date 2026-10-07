"""The Add Analyzer wizard's "I have a hosted API or model" path, end to end: save, promote to an
http: registration, readiness, Execution Test against a local stand-in service, and delete.
The Python path is covered in test_analyzer_labs_api.py and must not change."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator

import pytest
import yaml
from fastapi.testclient import TestClient

from backend.app.api import admin_analyzers, analyzer_labs
from backend.app.main import create_app


class _Service:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.findings: list[dict[str, Any]] = []
        service = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                service.calls.append(f"GET {self.path}")
                self._send({"status": "ok"})

            def do_POST(self) -> None:  # noqa: N802
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                service.calls.append(f"POST {self.path}")
                self._send({"findings": service.findings})

            def log_message(self, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture()
def service() -> Iterator[_Service]:
    fake = _Service()
    yield fake
    fake.server.shutdown()
    fake.server.server_close()


@pytest.fixture()
def registry_dir(tmp_path, monkeypatch):
    directory = tmp_path / "analyzer_registry.d"
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZERS_PATH", tmp_path / "custom_analyzers.yaml")
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZER_REGISTRY_DIR", directory)
    monkeypatch.setattr(analyzer_labs, "CUSTOM_ANALYZER_ADAPTER_DIR", tmp_path / "custom_adapters")
    monkeypatch.setattr(admin_analyzers, "CUSTOM_ANALYZER_REGISTRY_DIR", directory)
    monkeypatch.setattr(admin_analyzers, "CUSTOM_ANALYZER_ADAPTER_DIR", tmp_path / "custom_adapters")
    return directory


def _api_draft(analyze_url: str | None, health_check_url: str | None = None, api_key_env: str | None = None) -> dict:
    external_runtime: dict[str, Any] = {"type": "external_http"}
    if analyze_url:
        external_runtime["analyze_url"] = analyze_url
    if health_check_url:
        external_runtime["health_check_url"] = health_check_url
    if api_key_env:
        external_runtime["api_key_env"] = api_key_env
    return {
        "config": {
            "analyzer_id": "remote_forecast",
            "display_name": "Remote Forecast",
            "template_type": "External API",
            "library": "http",
            "enabled": True,
            "runtime_mapping": "not_implemented",
            "supported_profiles": ["seasonal"],
            "min_samples": 30,
            "base_score": 0.3,
            "scoring_rules": [{"metric": "seasonality_strength", "operator": "gte", "threshold": 0.4, "add": 0.2}],
            "runtime_params": {"quantile": 0.9, "external_runtime": external_runtime},
            "selected_explanation": "Seasonal series.",
            "excluded_explanation": "Not seasonal.",
        }
    }


def test_api_draft_needs_an_http_analyze_url(registry_dir) -> None:
    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
        missing = client.post("/api/analyzer-labs/drafts", json=_api_draft(None))
        assert missing.status_code == 422
        assert "Analyze URL" in missing.json()["detail"]

        wrong_scheme = client.post("/api/analyzer-labs/drafts", json=_api_draft("ftp://models/analyze"))
        assert wrong_scheme.status_code == 422
        assert "http://" in wrong_scheme.json()["detail"]


def test_api_analyzer_promotes_runs_and_deletes(registry_dir, service: _Service) -> None:
    service.findings = [{"start_time": "2026-10-01T00:00:00Z", "summary": "Above the forecast band.", "severity": "high"}]
    payload = _api_draft(f"{service.url}/analyze", f"{service.url}/health", api_key_env="REMOTE_FORECAST_KEY")

    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
        draft = client.post("/api/analyzer-labs/drafts", json=payload).json()

        preview = client.get(f"/api/analyzer-labs/drafts/{draft['id']}/yaml-preview").json()["yaml_text"]
        assert "analyze_url:" in preview
        assert "class_path" not in preview

        promoted = client.post(f"/api/analyzer-labs/drafts/{draft['id']}/promote", json={})
        assert promoted.status_code == 200
        assert promoted.json()["status"] == "executable"

        entry = yaml.safe_load((registry_dir / "custom_remote_forecast.yml").read_text())["analyzers"]["remote_forecast"]
        assert "class_path" not in entry
        assert entry["http"] == {
            "analyze_url": f"{service.url}/analyze",
            "health_check_url": f"{service.url}/health",
            "api_key_env": "REMOTE_FORECAST_KEY",
        }
        assert entry["router"]["supported_profiles"] == ["seasonal"]

        readiness = client.get(
            "/api/analyzer-labs/readiness/remote_forecast",
            params={"library": "http", "import_name": "http", "runtime_mapping": "not_implemented"},
        ).json()
        assert readiness["backend_implementation_exists"] is True
        assert readiness["executable"] is True

        listed = {item["analyzer_id"]: item for item in client.get("/api/admin/analyzers").json()}
        assert listed["remote_forecast"]["executable"] is True
        assert listed["remote_forecast"]["implementation_status"] == "http"

        support = client.post(f"/api/analyzer-labs/drafts/{draft['id']}/backend-support", json={})
        assert support.status_code == 400
        assert "doesn't need" in support.json()["detail"]

        execution = client.post(f"/api/analyzer-labs/drafts/{draft['id']}/execution-test", json={}).json()
        assert execution["status"] == "passed", execution["reason"]
        assert execution["signal_count"] == 1
        assert f"{service.url}/analyze" in execution["reason"]
        assert service.calls == ["GET /health", "POST /analyze"]

        deleted = client.delete("/api/analyzer-labs/analyzers/remote_forecast").json()
        assert deleted["registration"] is True
        assert deleted["code_file"] is False
        assert not (registry_dir / "custom_remote_forecast.yml").exists()


def test_execution_test_reports_a_service_that_is_down(registry_dir) -> None:
    payload = _api_draft("http://127.0.0.1:9/analyze", "http://127.0.0.1:9/health")

    with TestClient(create_app("sqlite+pysqlite:///:memory:")) as client:
        draft = client.post("/api/analyzer-labs/drafts", json=payload).json()
        client.post(f"/api/analyzer-labs/drafts/{draft['id']}/promote", json={})

        execution = client.post(f"/api/analyzer-labs/drafts/{draft['id']}/execution-test", json={}).json()

        assert execution["status"] == "failed"
        assert "Health check" in execution["reason"]
        assert "127.0.0.1:9" in execution["reason"]
