from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.ai.exceptions import LLMRequestError
from backend.app.ai.factory import OptionalAIServices
from backend.app.ai.interfaces import LLMClient, LLMRequest, LLMResponse
from backend.app.ai.models import StructuredLLMService
from backend.app.api import assistant as assistant_module
from backend.app.api.autonomous import get_prometheus_query_service
from backend.app.assistant.service import AssistantServices, OperationalIntelligenceAssistant
from backend.app.autonomous import execution as autonomous_execution
from backend.app.autonomous.schemas import DiscoveredMetric
from backend.app.main import create_app


class _FakeMetadataProvider:
    def __init__(self, metrics: list[DiscoveredMetric]) -> None:
        self.metrics = metrics

    def discover_metric_metadata(self, **kwargs):
        return list(self.metrics)

    def label_values(self, label: str):
        return sorted({metric.labels[label] for metric in self.metrics if label in metric.labels})

    def preview(self, query: str, start, end, step: str):
        from backend.app.models.prometheus import PrometheusPreviewOut, PrometheusSeriesOut, PrometheusSeriesSample

        samples = [PrometheusSeriesSample(timestamp=start + (end - start) * (idx / 30), value=float(idx)) for idx in range(31)]
        return PrometheusPreviewOut(
            query=query,
            start=start,
            end=end,
            step=step,
            step_seconds=600,
            series_count=1,
            sample_count=len(samples),
            series=[PrometheusSeriesOut(labels={"__name__": "cpu_usage", "service": "checkout"}, samples=samples)],
            warnings=[],
        )


class _FakeMetricAnalysisExecutor:
    def __init__(self, config) -> None:
        self.config = config

    def execute_dataframe(self, dataframe, *, run_metadata=None, db=None):
        return type("Result", (), {"analysis_run_id": "analysis-run-cpu", "signal_count": 1, "findings_count": 1, "behavior_findings_count": 0})()


def _metric(name: str) -> DiscoveredMetric:
    return DiscoveredMetric(
        metric_name=name,
        labels={"__name__": name, "service": "checkout"},
        service="checkout",
        namespace="commerce",
        environment="production",
        source="prometheus",
    )


class _FakeLLMClient(LLMClient):
    def __init__(self, *, response: str | None = None, should_fail: bool = False) -> None:
        self.response = response
        self.should_fail = should_fail
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self.should_fail:
            raise LLMRequestError("simulated failure")
        return LLMResponse(content=self.response or "", model="fake-model", provider="fake")


def _assistant_with(client: LLMClient | None) -> OperationalIntelligenceAssistant:
    ai_services = OptionalAIServices(client=client, structured=StructuredLLMService(client)) if client else None
    return OperationalIntelligenceAssistant(
        AssistantServices(embedder=None, case_similarity=None, docs_store=None, ai_services=ai_services)
    )


def _run_once_and_ask(monkeypatch, question: str, assistant_override) -> dict:
    monkeypatch.setattr(autonomous_execution, "MetricAnalysisExecutor", _FakeMetricAnalysisExecutor)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: _FakeMetadataProvider([_metric("cpu_usage")])
    if assistant_override is not None:
        app.dependency_overrides[assistant_module.get_assistant] = lambda: assistant_override

    with TestClient(app) as client:
        run_response = client.post(
            "/api/autonomous/run-once",
            json={
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["capacity"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
            },
        ).json()
        answer_response = client.post(
            "/api/autonomous/questions/answer",
            json={"policy_run_id": run_response["policy_run_id"], "question": question, "window": "24h"},
        )
    assert answer_response.status_code == 200
    return answer_response.json()


def test_answer_uses_llm_synthesis_when_ai_is_enabled(monkeypatch) -> None:
    fake_client = _FakeLLMClient(response="The run completed with one CPU finding on checkout.")
    answer = _run_once_and_ask(monkeypatch, "Summarize this run", _assistant_with(fake_client))

    assert answer["ai_synthesis_used"] is True
    assert answer["answer"] == "The run completed with one CPU finding on checkout."
    # headline/priority/evidence stay deterministic regardless of LLM synthesis.
    assert answer["evidence"]["policy_run_id"]


def test_answer_falls_back_to_the_deterministic_template_when_ai_is_disabled(monkeypatch) -> None:
    answer = _run_once_and_ask(monkeypatch, "Summarize this run", _assistant_with(None))

    assert answer["ai_synthesis_used"] is False
    assert "generated from stored autonomous run" in answer["answer"]


def test_answer_falls_back_to_the_deterministic_template_when_the_llm_call_fails(monkeypatch) -> None:
    fake_client = _FakeLLMClient(should_fail=True)
    answer = _run_once_and_ask(monkeypatch, "Summarize this run", _assistant_with(fake_client))

    assert answer["ai_synthesis_used"] is False
    assert "generated from stored autonomous run" in answer["answer"]


def test_answer_never_calls_the_llm_when_there_is_no_run_data() -> None:
    fake_client = _FakeLLMClient(response="should never be used")
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[assistant_module.get_assistant] = lambda: _assistant_with(fake_client)

    with TestClient(app) as client:
        response = client.post("/api/autonomous/questions/answer", json={"question": "Summarize this run", "window": "24h"})

    assert response.status_code == 200
    body = response.json()
    assert body["ai_synthesis_used"] is False
    assert fake_client.requests == []
