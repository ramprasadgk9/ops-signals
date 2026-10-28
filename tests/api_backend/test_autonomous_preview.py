from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.autonomous import execution as autonomous_execution
from backend.app.api.autonomous import get_prometheus_query_service
from backend.app.autonomous.schemas import AnalysisScope, CustomMetricConstraints, DiscoveredMetric, ExecutionPolicy, MetricConcept, MetricDiscoveryResult, MonitoringCategory
from backend.app.autonomous.services import MetricClassificationService, MetricDiscoveryService, MetricPlanBuilder, build_label_matcher, build_scope_selector, validate_label_name
from backend.app.config import PrometheusConnectionConfig
from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import FindingEntity
from backend.app.models.prometheus import PrometheusPreviewOut, PrometheusSeriesOut, PrometheusSeriesSample
from backend.app.services.prometheus_service import PrometheusQueryService


class FakeMetadataProvider:
    def __init__(self, metrics: list[DiscoveredMetric]):
        self.metrics = metrics

    def discover_metric_metadata(self, **kwargs):
        return list(self.metrics)

    def label_values(self, label: str, **kwargs):
        values = sorted({metric.labels[label] for metric in self.metrics if label in metric.labels})
        return values

    def preview(self, query: str, start, end, step: str):
        samples = [
            PrometheusSeriesSample(timestamp=start + (end - start) * (idx / 30), value=float(idx))
            for idx in range(31)
        ]
        metric_name = "memory_usage" if "memory_usage" in query else "cpu_usage"
        service = "payments" if "payments" in query else "checkout"
        return PrometheusPreviewOut(
            query=query,
            start=start,
            end=end,
            step=step,
            step_seconds=600,
            series_count=1,
            sample_count=len(samples),
            series=[PrometheusSeriesOut(labels={"__name__": metric_name, "service": service}, samples=samples)],
            warnings=[],
        )


class FakeFailingProvider(FakeMetadataProvider):
    def __init__(self, metrics: list[DiscoveredMetric], fail_all: bool = False):
        super().__init__(metrics)
        self.fail_all = fail_all

    def preview(self, query: str, start, end, step: str):
        if self.fail_all or "memory_usage" in query:
            raise ValueError("synthetic prometheus failure")
        return super().preview(query, start, end, step)


class FakeMetricAnalysisExecutor:
    def __init__(self, config):
        self.config = config

    def execute_dataframe(self, dataframe, *, run_metadata=None, db=None):
        metric = str(run_metadata.get("promql", "metric")) if run_metadata else "metric"
        suffix = "memory" if "memory_usage" in metric else "cpu"
        return type(
            "Result",
            (),
            {
                "analysis_run_id": f"analysis-run-{suffix}",
                "signal_count": 1,
                "findings_count": 1 if suffix == "cpu" else 0,
                "behavior_findings_count": 0,
            },
        )()


def metric(name: str, service: str | None = "checkout", namespace: str | None = "commerce", env: str | None = "production", labels: dict | None = None):
    metric_labels = {"__name__": name}
    if service:
        metric_labels["service"] = service
    if namespace:
        metric_labels["namespace"] = namespace
    if env:
        metric_labels["env"] = env
    metric_labels.update(labels or {})
    return DiscoveredMetric(metric_name=name, labels=metric_labels, service=service, namespace=namespace, environment=env, source="prometheus")


def build_plan(metrics: list[DiscoveredMetric], scope: AnalysisScope | None = None, categories: list[MonitoringCategory] | None = None, max_metrics: int = 500, custom: CustomMetricConstraints | None = None):
    resolved, discovered = MetricDiscoveryService(FakeMetadataProvider(metrics)).discover(scope or AnalysisScope())
    return MetricPlanBuilder().build(
        resolved_scope=resolved,
        discovered_metrics=discovered,
        selected_categories=categories or [MonitoringCategory.performance, MonitoringCategory.capacity, MonitoringCategory.availability],
        execution=ExecutionPolicy(max_metrics_per_run=max_metrics),
        custom_constraints=custom or CustomMetricConstraints(),
        classifier=MetricClassificationService(),
    )


def test_all_services_scope_resolution() -> None:
    resolved, discovered = MetricDiscoveryService(FakeMetadataProvider([metric("cpu_usage", "checkout"), metric("memory_usage", "payments")])).discover(AnalysisScope(all_services=True))
    assert resolved.resolved_services == ["checkout", "payments"]
    assert len(discovered) == 2


def test_all_services_plan_builds_single_service_queries() -> None:
    plan = build_plan([metric("cpu_usage", "checkout"), metric("memory_usage", "payments")], AnalysisScope(all_services=True), categories=[MonitoringCategory.capacity])
    planned = {item.metric_name: item.promql for item in plan.items if item.planned}
    assert 'cpu_usage{' in planned["cpu_usage"]
    assert 'service="checkout"' in planned["cpu_usage"]
    assert 'env="production"' in planned["cpu_usage"]
    assert 'memory_usage{' in planned["memory_usage"]
    assert 'service="payments"' in planned["memory_usage"]
    assert 'env="production"' in planned["memory_usage"]


def test_selected_service_filtering() -> None:
    plan = build_plan([metric("cpu_usage", "checkout"), metric("memory_usage", "payments")], AnalysisScope(all_services=False, services=["payments"]))
    assert plan.total_metrics_discovered == 1
    assert plan.items[0].service == "payments"
    assert 'service="payments"' in plan.items[0].promql


def test_namespace_filtering() -> None:
    plan = build_plan([metric("cpu_usage", namespace="commerce"), metric("cpu_usage", namespace="platform")], AnalysisScope(all_namespaces=False, namespaces=["platform"]))
    assert plan.total_metrics_discovered == 1
    assert plan.items[0].namespace == "platform"


def test_missing_service_label_warns_without_failure() -> None:
    resolved, discovered = MetricDiscoveryService(FakeMetadataProvider([metric("cpu_usage", service=None)])).discover(AnalysisScope(service_label="app"))
    assert discovered
    assert any("No services were found" in warning for warning in resolved.warnings)


def test_empty_discovery_result() -> None:
    resolved, discovered = MetricDiscoveryService(FakeMetadataProvider([])).discover(AnalysisScope())
    assert discovered == []
    assert resolved.discovered_metric_count == 0


def test_category_to_concept_expansion() -> None:
    plan = build_plan([metric("cpu_usage")], categories=[MonitoringCategory.capacity])
    assert MetricConcept.cpu in plan.items[0].concepts
    assert "cpu" in plan.monitoring_summary["concepts"]


def test_exact_metric_classification() -> None:
    plan = build_plan([metric("container_cpu_usage_seconds_total")], categories=[MonitoringCategory.capacity])
    assert plan.items[0].planned is True
    assert plan.items[0].selection_reason == "exact_metric_mapping"
    assert plan.items[0].concept == MetricConcept.cpu


def test_regex_classification() -> None:
    plan = build_plan([metric("service_latency_seconds")], categories=[MonitoringCategory.performance])
    assert plan.items[0].planned is True
    assert plan.items[0].selection_reason == "metric_name_pattern"


def test_metadata_metric_exclusion() -> None:
    plan = build_plan([metric("build_info")], categories=[MonitoringCategory.infrastructure])
    assert plan.items[0].planned is False
    assert plan.items[0].exclusion_reason == "static_metadata_metric"


def test_created_metric_exclusion() -> None:
    plan = build_plan([metric("http_requests_created")], categories=[MonitoringCategory.performance])
    assert plan.items[0].planned is False
    assert plan.items[0].exclusion_reason == "created_timestamp"


def test_custom_include_and_exclude_behavior() -> None:
    custom = CustomMetricConstraints(include_patterns=["custom_.*"], exclude_patterns=["custom_ignore_.*"])
    plan = build_plan([metric("custom_latency"), metric("custom_ignore_latency")], categories=[MonitoringCategory.custom], custom=custom)
    assert plan.items[0].planned is True
    assert plan.items[0].selection_reason == "custom_include_pattern"
    assert plan.items[1].planned is False
    assert plan.items[1].exclusion_reason == "custom_exclude_pattern"
    # The UI shows this so users can see exactly which of their own patterns matched,
    # not just that "a" pattern matched.
    assert plan.items[1].matched_rule == "custom.exclude.custom_ignore_.*"


def test_exclusion_reason_names_the_matched_static_rule() -> None:
    plan = build_plan([metric("build_info")], categories=[MonitoringCategory.infrastructure])
    assert plan.items[0].matched_rule == "static.suffix._info"


def test_multi_category_classification() -> None:
    plan = build_plan([metric("container_cpu_usage_seconds_total")], categories=[MonitoringCategory.capacity, MonitoringCategory.infrastructure])
    assert plan.items[0].planned is True
    assert plan.items[0].category in {MonitoringCategory.capacity, MonitoringCategory.infrastructure}


def test_category_disabled_exclusion_reports_would_be_category() -> None:
    """A metric that matches a known rule but whose category isn't enabled should be
    distinguishable from a metric nobody has a rule for - the former is fixable by
    enabling a category, the latter isn't."""
    plan = build_plan([metric("container_cpu_usage_seconds_total")], categories=[MonitoringCategory.availability])
    assert plan.items[0].planned is False
    assert plan.items[0].exclusion_reason == "category_disabled"
    assert MonitoringCategory.capacity in plan.items[0].would_be_category


def test_unrecognized_metric_name_is_not_marked_category_disabled() -> None:
    plan = build_plan([metric("totally_unrecognized_custom_metric_xyz")], categories=[MonitoringCategory.performance])
    assert plan.items[0].planned is False
    assert plan.items[0].exclusion_reason == "no_matching_rule"
    assert plan.items[0].would_be_category == []


def test_budget_enforcement() -> None:
    plan = build_plan([metric("cpu_usage", "a"), metric("memory_usage", "b")], categories=[MonitoringCategory.capacity], max_metrics=1)
    assert plan.planned_jobs == 1
    assert plan.budget_limited_jobs == 1


def test_small_budget_prefers_demo_signal_services() -> None:
    plan = build_plan(
        [
            metric("cpu_usage", "checkout"),
            metric("cpu_usage", "spike-lab"),
            metric("memory_usage", "payments"),
        ],
        scope=AnalysisScope(all_services=True),
        categories=[MonitoringCategory.capacity],
        max_metrics=1,
    )
    planned = [item for item in plan.items if item.planned]
    assert len(planned) == 1
    assert planned[0].service == "spike-lab"
    assert 'service="spike-lab"' in planned[0].promql
    assert plan.items[0].planned is True
    assert plan.items[0].service == "spike-lab"


def test_duplicate_metric_removal_and_service_grouping() -> None:
    plan = build_plan([metric("cpu_usage", "checkout"), metric("cpu_usage", "checkout")], categories=[MonitoringCategory.capacity])
    assert plan.total_metrics_discovered == 1
    assert plan.items[0].estimated_series_count == 2
    assert plan.items[0].aggregation_strategy == "avg_by_service"


def test_invalid_label_key_rejection() -> None:
    try:
        validate_label_name("bad-label", "service_label")
    except ValueError as exc:
        assert "valid Prometheus label name" in str(exc)
    else:
        raise AssertionError("invalid label was accepted")


def test_single_value_selector_generation() -> None:
    assert build_label_matcher("service", ["payments"]) == 'service="payments"'


def test_multi_value_regex_selector_generation() -> None:
    assert build_label_matcher("service", ["payments", "checkout"]) == 'service=~"checkout|payments"'


def test_all_services_and_namespaces_selector_behavior() -> None:
    selector = build_scope_selector(AnalysisScope(environment="production", services=["payments"], all_services=True, namespaces=["commerce"], all_namespaces=True))
    assert selector == '{env="production"}'


def test_counter_rate_query() -> None:
    plan = build_plan([metric("container_cpu_usage_seconds_total")], categories=[MonitoringCategory.capacity])
    assert "rate(container_cpu_usage_seconds_total" in plan.items[0].promql
    assert plan.items[0].transformation == "rate"


def test_gauge_aggregation_query() -> None:
    plan = build_plan([metric("container_memory_working_set_bytes")], categories=[MonitoringCategory.capacity])
    assert plan.items[0].promql.startswith("avg by (service)")
    assert "rate(" not in plan.items[0].promql


def test_histogram_p95_query() -> None:
    plan = build_plan([metric("http_request_duration_seconds_bucket", labels={"le": "0.5"})], categories=[MonitoringCategory.performance])
    assert "histogram_quantile(0.95" in plan.items[0].promql
    assert "sum by (le, service)" in plan.items[0].promql


def test_duplicate_concept_ranking() -> None:
    plan = build_plan([metric("cpu_usage", "checkout"), metric("process_cpu_seconds_total", "checkout")], categories=[MonitoringCategory.capacity])
    planned = [item for item in plan.items if item.planned]
    excluded = [item for item in plan.items if item.exclusion_reason == "duplicate_lower_rank"]
    assert len(planned) == 1
    assert len(excluded) == 1


CHECKOUT_CUSTOM_METRICS = [
    "checkout_orders_total",
    "checkout_payment_failures_total",
    "checkout_cart_abandon_total",
    "checkout_refunds_total",
    "checkout_queue_depth",
]


def test_every_explicit_custom_metric_gets_its_own_job() -> None:
    plan = build_plan(
        [metric(name, "checkout") for name in CHECKOUT_CUSTOM_METRICS],
        categories=[MonitoringCategory.custom],
        custom=CustomMetricConstraints(explicit_metrics=CHECKOUT_CUSTOM_METRICS),
    )

    assert sorted(item.metric_name for item in plan.items if item.planned) == sorted(CHECKOUT_CUSTOM_METRICS)
    assert not [item for item in plan.items if item.exclusion_reason == "duplicate_lower_rank"]


def test_every_custom_pattern_match_gets_its_own_job() -> None:
    plan = build_plan(
        [metric(name, "checkout") for name in CHECKOUT_CUSTOM_METRICS],
        categories=[MonitoringCategory.custom],
        custom=CustomMetricConstraints(include_patterns=["checkout_.*"]),
    )

    assert len([item for item in plan.items if item.planned]) == len(CHECKOUT_CUSTOM_METRICS)


def test_custom_metric_sampled_from_several_series_is_still_one_job() -> None:
    """Discovery hands the planner several example series per metric; they are one job, not one each."""
    pods = [metric("checkout_orders_total", "checkout", labels={"pod": f"pod-{index}"}) for index in range(3)]
    plan = build_plan(pods, categories=[MonitoringCategory.custom], custom=CustomMetricConstraints(explicit_metrics=["checkout_orders_total"]))

    assert len([item for item in plan.items if item.planned]) == 1


def test_custom_metric_is_one_job_per_service() -> None:
    plan = build_plan(
        [metric("checkout_orders_total", "checkout"), metric("checkout_orders_total", "payments")],
        AnalysisScope(all_services=True),
        categories=[MonitoringCategory.custom],
        custom=CustomMetricConstraints(explicit_metrics=["checkout_orders_total"]),
    )

    assert sorted(item.service for item in plan.items if item.planned) == ["checkout", "payments"]


def test_preview_api_validation_and_response() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeMetadataProvider([metric("http_request_duration_seconds")])
    with TestClient(app) as client:
        response = client.post(
            "/api/autonomous/preview",
            json={
                "datasource": "prometheus",
                "backend": "grafana-stack",
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["performance"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
            },
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["planned_jobs"] == 1
    assert payload["monitoring_summary"]["concepts"]
    assert payload["items"][0]["promql"]


def test_run_once_dry_run_returns_planned_jobs_without_execution() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeMetadataProvider([metric("cpu_usage", "checkout")])
    with TestClient(app) as client:
        response = client.post(
            "/api/autonomous/run-once",
            json={
                "datasource": "prometheus",
                "backend": "grafana-stack",
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["capacity"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
                "dry_run": True,
            },
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "dry_run"
    assert payload["policy_run_id"]
    assert payload["planned_jobs"] == 1
    assert payload["executed_jobs"] == 0
    assert payload["results"][0]["status"] == "skipped"
    assert payload["results"][0]["job_id"]


def test_preview_api_requires_category() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        response = client.post("/api/autonomous/preview", json={"monitoring_categories": []})
    assert response.status_code == 422


def test_scope_options_api_returns_backend_metadata() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeMetadataProvider([metric("cpu_usage", "checkout", "commerce"), metric("memory_usage", "payments", "billing")])
    with TestClient(app) as client:
        response = client.get("/api/autonomous/scope-options")
    assert response.status_code == 200
    assert response.json()["services"] == ["checkout", "payments"]
    assert response.json()["namespaces"] == ["billing", "commerce"]


def test_run_once_creates_policy_run_and_completed_job(monkeypatch) -> None:
    monkeypatch.setattr(autonomous_execution, "MetricAnalysisExecutor", FakeMetricAnalysisExecutor)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeMetadataProvider([metric("cpu_usage", "checkout")])
    with TestClient(app) as client:
        response = client.post(
            "/api/autonomous/run-once",
            json={
                "datasource": "prometheus",
                "backend": "grafana-stack",
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["capacity"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
            },
        )
        payload = response.json()
        run_response = client.get(f"/api/autonomous/policy-runs/{payload['policy_run_id']}")
        jobs_response = client.get(f"/api/autonomous/policy-runs/{payload['policy_run_id']}/jobs")
    assert response.status_code == 200
    assert payload["status"] == "completed"
    assert payload["summary"]["jobs_completed"] == 1
    assert run_response.json()["status"] == "completed"
    assert jobs_response.json()[0]["analysis_run_id"] == "analysis-run-cpu"
    assert jobs_response.json()[0]["status"] == "completed"


def test_multiple_planned_metrics_create_multiple_jobs(monkeypatch) -> None:
    monkeypatch.setattr(autonomous_execution, "MetricAnalysisExecutor", FakeMetricAnalysisExecutor)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeMetadataProvider([metric("cpu_usage", "checkout"), metric("memory_usage", "payments")])
    with TestClient(app) as client:
        response = client.post(
            "/api/autonomous/run-once",
            json={
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["capacity"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
            },
        )
        jobs = client.get(f"/api/autonomous/policy-runs/{response.json()['policy_run_id']}/jobs").json()
    assert response.status_code == 200
    assert response.json()["planned_jobs"] == 2
    assert len(jobs) == 2
    assert {job["metric_name"] for job in jobs} == {"cpu_usage", "memory_usage"}


def test_skipped_job_persists_skip_reason(monkeypatch) -> None:
    monkeypatch.setattr(autonomous_execution, "MetricAnalysisExecutor", FakeMetricAnalysisExecutor)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeMetadataProvider([metric("cpu_usage", "checkout"), metric("request_latency_p95", "checkout")])
    with TestClient(app) as client:
        response = client.post(
            "/api/autonomous/run-once",
            json={
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["capacity"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
            },
        )
        jobs = client.get(f"/api/autonomous/policy-runs/{response.json()['policy_run_id']}/jobs").json()
    skipped = [job for job in jobs if job["status"] == "screened_out"]
    assert skipped
    assert skipped[0]["skip_reason_code"] == "category_not_selected"
    assert skipped[0]["skip_reason_detail"]


def test_one_job_failure_keeps_success_and_marks_run_partial(monkeypatch) -> None:
    monkeypatch.setattr(autonomous_execution, "MetricAnalysisExecutor", FakeMetricAnalysisExecutor)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeFailingProvider([metric("cpu_usage", "checkout"), metric("memory_usage", "payments")])
    with TestClient(app) as client:
        response = client.post(
            "/api/autonomous/run-once",
            json={
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["capacity"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
            },
        )
        payload = response.json()
        jobs = client.get(f"/api/autonomous/policy-runs/{payload['policy_run_id']}/jobs").json()
    assert payload["status"] == "partial"
    assert payload["executed_jobs"] == 1
    assert payload["failed_jobs"] == 1
    assert any(job["status"] == "completed" and job["analysis_run_id"] == "analysis-run-cpu" for job in jobs)
    assert any(job["status"] == "failed" and job["error_type"] == "ValueError" for job in jobs)


def test_all_failed_jobs_mark_policy_run_failed(monkeypatch) -> None:
    monkeypatch.setattr(autonomous_execution, "MetricAnalysisExecutor", FakeMetricAnalysisExecutor)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeFailingProvider([metric("cpu_usage", "checkout")], fail_all=True)
    with TestClient(app) as client:
        response = client.post(
            "/api/autonomous/run-once",
            json={
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["capacity"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
            },
        )
        run = client.get(f"/api/autonomous/policy-runs/{response.json()['policy_run_id']}").json()
    assert response.json()["status"] == "failed"
    assert run["status"] == "failed"
    assert run["jobs_failed"] == 1


def test_policy_snapshot_is_historical_copy(monkeypatch) -> None:
    monkeypatch.setattr(autonomous_execution, "MetricAnalysisExecutor", FakeMetricAnalysisExecutor)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeMetadataProvider([metric("cpu_usage", "checkout")])
    request_payload = {
        "scope": {"all_services": True, "all_namespaces": True},
        "monitoring_categories": ["capacity"],
        "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
    }
    with TestClient(app) as client:
        response = client.post("/api/autonomous/run-once", json=request_payload)
        request_payload["execution"]["analysis_window"] = "7d"
        run = client.get(f"/api/autonomous/policy-runs/{response.json()['policy_run_id']}").json()
    assert run["policy_snapshot"]["execution_policy"]["analysis_window"] == "24h"


def test_autonomous_policy_run_history_endpoint_returns_runs(monkeypatch) -> None:
    monkeypatch.setattr(autonomous_execution, "MetricAnalysisExecutor", FakeMetricAnalysisExecutor)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeMetadataProvider([metric("cpu_usage", "checkout")])
    with TestClient(app) as client:
        run_response = client.post(
            "/api/autonomous/run-once",
            json={
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["capacity"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
            },
        )
        history = client.get("/api/autonomous/policy-runs").json()
    assert any(row["policy_run_id"] == run_response.json()["policy_run_id"] for row in history)


def test_autonomous_jobs_endpoint_returns_only_requested_policy_run(monkeypatch) -> None:
    monkeypatch.setattr(autonomous_execution, "MetricAnalysisExecutor", FakeMetricAnalysisExecutor)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeMetadataProvider([metric("cpu_usage", "checkout")])
    with TestClient(app) as client:
        first = client.post(
            "/api/autonomous/run-once",
            json={
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["capacity"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
            },
        ).json()
        second = client.post(
            "/api/autonomous/run-once",
            json={
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["capacity"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
            },
        ).json()
        first_jobs = client.get(f"/api/autonomous/policy-runs/{first['policy_run_id']}/jobs").json()
        second_jobs = client.get(f"/api/autonomous/policy-runs/{second['policy_run_id']}/jobs").json()
    assert first_jobs
    assert second_jobs
    assert {job["policy_run_id"] for job in first_jobs} == {first["policy_run_id"]}
    assert {job["policy_run_id"] for job in second_jobs} == {second["policy_run_id"]}


def test_findings_search_filters_recent_stored_findings() -> None:
    app = create_app("sqlite+pysqlite:///:memory:")
    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            db.add(
                FindingEntity(
                    service="checkout",
                    metric_name="latency_p95",
                    title="checkout latency shifted upward",
                    summary="latency_p95 experienced a persistent baseline shift.",
                    category="Behavior Change",
                    health_status="significant",
                    importance_score=0.91,
                    investigation_priority=1,
                    signal_ids=["signal-1"],
                    comparison_json={"before": 180, "after": 650},
                    analysis_run_id="analysis-run-latency",
                    created_at=datetime.now(timezone.utc),
                )
            )
            db.commit()
        response = client.get("/api/findings/search?window=1h&q=latency&service=checkout")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["metric_name"] == "latency_p95"


def test_autonomous_question_answer_uses_run_evidence(monkeypatch) -> None:
    monkeypatch.setattr(autonomous_execution, "MetricAnalysisExecutor", FakeMetricAnalysisExecutor)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeMetadataProvider([metric("cpu_usage", "checkout"), metric("request_latency_p95", "checkout")])
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
            json={"policy_run_id": run_response["policy_run_id"], "question": "Which metrics were skipped?", "window": "24h"},
        )
    assert answer_response.status_code == 200
    answer = answer_response.json()
    assert "skipped" in answer["headline"].lower()
    assert answer["evidence"]["policy_run_id"] == run_response["policy_run_id"]
    assert answer["evidence"]["job_ids"]


def test_autonomous_code_does_not_import_signal_pipeline() -> None:
    autonomous_files = [
        path
        for path in Path(__file__).resolve().parents[2].joinpath("backend", "app", "autonomous").glob("*.py")
    ]
    for path in autonomous_files:
        source = path.read_text()
        assert "from intelligence.pipeline import SignalPipeline" not in source
        assert "import SignalPipeline" not in source
        assert "SignalPipeline(" not in source


def test_scoped_policy_pushes_scope_selector_down() -> None:
    captured_args = {}

    class TrackingProvider:
        def discover_metric_metadata(self, **kwargs):
            captured_args.update(kwargs)
            return MetricDiscoveryResult(
                metrics=[
                    DiscoveredMetric(
                        metric_name="checkout_latency",
                        labels={"__name__": "checkout_latency", "service": "checkout"},
                        service="checkout",
                        source="prometheus",
                    )
                ],
                series_discovered=1,
            )

    discovery = MetricDiscoveryService(TrackingProvider())
    scope = AnalysisScope(services=["checkout"], all_services=False)
    resolved_scope, discovered = discovery.discover(scope)

    assert captured_args.get("scope_selector") == '{service="checkout"}'
    assert resolved_scope.selector == '{service="checkout"}'
    assert len(discovered) == 1
    assert discovered[0].metric_name == "checkout_latency"


def test_breadth_first_discovery_prevents_alphabetical_starvation() -> None:
    prom = PrometheusQueryService(PrometheusConnectionConfig(base_url="http://mock-prom:9090"))

    def fake_get_json(path, params):
        if "/api/v1/label/__name__/values" in path:
            return {
                "status": "success",
                "data": ["apiserver_request_duration_seconds", "business_orders_total", "zebra_queue_depth"],
            }
        if "/api/v1/metadata" in path:
            return {
                "status": "success",
                "data": {
                    "apiserver_request_duration_seconds": [{"type": "counter"}],
                    "business_orders_total": [{"type": "counter"}],
                    "zebra_queue_depth": [{"type": "gauge"}],
                },
            }
        if "/api/v1/series" in path:
            apiserver_series = [
                {"__name__": "apiserver_request_duration_seconds", "service": "apiserver", "instance": f"pod-{i}"}
                for i in range(500)
            ]
            business_series = [
                {"__name__": "business_orders_total", "service": "orders", "instance": f"pod-{i}"}
                for i in range(3)
            ]
            zebra_series = [
                {"__name__": "zebra_queue_depth", "service": "zebra", "instance": f"pod-{i}"}
                for i in range(2)
            ]
            return {"status": "success", "data": apiserver_series + business_series + zebra_series}
        return {"status": "success", "data": []}

    prom._get_json = fake_get_json

    result = prom.discover_metric_metadata(limit=20, max_series_per_metric=5)

    discovered_names = {m.metric_name for m in result.metrics}
    assert "apiserver_request_duration_seconds" in discovered_names
    assert "business_orders_total" in discovered_names
    assert "zebra_queue_depth" in discovered_names
    assert result.truncated is False
    assert len(result.starved_metrics) == 0


def test_discovery_truncation_reported_in_scope_and_preview() -> None:
    class TruncatedProvider:
        def discover_metric_metadata(self, **kwargs):
            return MetricDiscoveryResult(
                metrics=[
                    DiscoveredMetric(
                        metric_name="metric_a",
                        labels={"__name__": "metric_a", "service": "a"},
                        service="a",
                        source="prometheus",
                    )
                ],
                series_available=50000,
                series_discovered=5000,
                truncated=True,
                starved_metrics=["metric_y", "metric_z"],
            )

    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: TruncatedProvider()

    with TestClient(app) as client:
        response = client.post(
            "/api/autonomous/preview",
            json={
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["capacity"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["truncated"] is True
    assert payload["starved_metrics_count"] == 2
    assert payload["series_discovered"] == 5000
    assert payload["series_available"] == 50000
    assert any("truncated by the metadata safety limit" in w for w in payload["warnings"])
    assert payload["scope_summary"]["truncated"] is True
    assert payload["scope_summary"]["starved_metrics_count"] == 2
    assert payload["starved_metrics"] == ["metric_y", "metric_z"]
    assert payload["scope_summary"]["starved_metrics"] == ["metric_y", "metric_z"]


def test_per_metric_cap_and_round_robin_sampling() -> None:
    # Verify per-metric cap (e.g. 100) and round-robin allocation across metrics
    metric_a_rows = [
        {"__name__": "metric_a", "service": "checkout", "pod": f"pod-a-{i}"}
        for i in range(150)
    ]
    metric_b_rows = [
        {"__name__": "metric_b", "service": "checkout", "pod": f"pod-b-{i}"}
        for i in range(10)
    ]

    # When limit=50 and max_per_metric=100, round-robin ensures metric_b gets its 10 series and metric_a gets 40
    sampled = PrometheusQueryService._sample_distinct_series(
        metric_a_rows + metric_b_rows,
        max_per_metric=100,
        limit=50,
    )
    assert len(sampled) == 50
    a_samples = [s for s in sampled if s["__name__"] == "metric_a"]
    b_samples = [s for s in sampled if s["__name__"] == "metric_b"]
    assert len(b_samples) == 10
    assert len(a_samples) == 40

    # Verify single metric cap applies up to max_per_metric
    single_metric_sampled = PrometheusQueryService._sample_distinct_series(
        metric_a_rows,
        max_per_metric=100,
        limit=500,
    )
    assert len(single_metric_sampled) == 100


def test_label_values_with_matchers_raises_on_http_error() -> None:
    prom = PrometheusQueryService(PrometheusConnectionConfig(base_url="http://mock-prom:9090"))

    def fake_get_json(path, params):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid matcher selector")

    prom._get_json = fake_get_json

    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        prom.label_values("__name__", matchers=['{service="bad"}'])
    assert exc_info.value.status_code == 400


def test_scoped_fast_path_anti_starvation_and_truncation() -> None:
    prom = PrometheusQueryService(PrometheusConnectionConfig(base_url="http://mock-prom:9090"))

    def fake_get_json(path, params):
        if "/api/v1/series" in path:
            # 100 series for metric_a and 2 series for metric_z
            metric_a_series = [
                {"__name__": "metric_a", "service": "checkout", "instance": f"pod-{i}"}
                for i in range(100)
            ]
            metric_z_series = [
                {"__name__": "metric_z", "service": "checkout", "instance": f"pod-{i}"}
                for i in range(2)
            ]
            return {"status": "success", "data": metric_a_series + metric_z_series}
        if "/api/v1/metadata" in path:
            return {
                "status": "success",
                "data": {
                    "metric_a": [{"type": "counter"}],
                    "metric_z": [{"type": "gauge"}],
                },
            }
        return {"status": "success", "data": []}

    prom._get_json = fake_get_json

    # When limit=5 and max_series_per_metric=2, round-robin ensures both metric_a and metric_z are discovered
    result = prom.discover_metric_metadata(
        scope_selector='{service="checkout"}',
        limit=5,
        max_series_per_metric=2,
    )

    discovered_names = {m.metric_name for m in result.metrics}
    assert "metric_a" in discovered_names
    assert "metric_z" in discovered_names
    assert result.series_available == 102
    assert result.series_discovered == 4  # 2 for metric_a (max_series_per_metric=2) + 2 for metric_z
    assert result.truncated is True
    assert result.starved_metrics == []


def test_sample_distinct_series_is_deterministic() -> None:
    # Shuffle input rows and ensure identical deterministic sampled output
    raw_rows_1 = [
        {"__name__": "metric_b", "service": "orders", "instance": "pod-1"},
        {"__name__": "metric_a", "service": "checkout", "instance": "pod-1"},
        {"__name__": "metric_a", "service": "checkout", "instance": "pod-2"},
        {"__name__": "metric_b", "service": "orders", "instance": "pod-2"},
    ]
    raw_rows_2 = list(reversed(raw_rows_1))

    sampled_1 = PrometheusQueryService._sample_distinct_series(raw_rows_1, max_per_metric=5, limit=10)
    sampled_2 = PrometheusQueryService._sample_distinct_series(raw_rows_2, max_per_metric=5, limit=10)

    assert sampled_1 == sampled_2


def test_preview_surfaces_budget_excluded_metrics() -> None:
    metrics = [
        metric("cpu_usage", "checkout"),
        metric("memory_usage", "payments"),
        metric("container_memory_working_set_bytes", "shipping"),
    ]
    plan = build_plan(metrics, max_metrics=1)

    assert plan.planned_jobs == 1
    assert plan.budget_limited_jobs == 2
    assert plan.budget_excluded_metrics_count == 2
    assert len(plan.budget_excluded_metrics) == 2
    assert plan.scope_summary["budget_limited_jobs"] == 2
    assert plan.scope_summary["budget_excluded_metrics_count"] == 2
    assert len(plan.scope_summary["budget_excluded_metrics"]) == 2
    assert any("Execution budget limited" in w and "Every run is independent" in w for w in plan.warnings)


def test_preview_api_surfaces_budget_excluded_metrics() -> None:
    metrics = [
        metric("cpu_usage", "checkout"),
        metric("memory_usage", "payments"),
        metric("container_memory_working_set_bytes", "shipping"),
    ]
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeMetadataProvider(metrics)
    with TestClient(app) as client:
        response = client.post(
            "/api/autonomous/preview",
            json={
                "datasource": "prometheus",
                "backend": "grafana-stack",
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["capacity"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 1, "max_parallel_jobs": 10},
            },
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["planned_jobs"] == 1
    assert payload["budget_limited_jobs"] == 2
    assert payload["budget_excluded_metrics_count"] == 2
    assert len(payload["budget_excluded_metrics"]) == 2
    assert any("Execution budget limited" in w and "Every run is independent" in w for w in payload["warnings"])



def test_run_once_surfaces_budget_excluded_metrics_in_response_and_summary() -> None:
    metrics = [
        metric("cpu_usage", "checkout"),
        metric("memory_usage", "payments"),
        metric("container_memory_working_set_bytes", "shipping"),
    ]
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeMetadataProvider(metrics)
    with TestClient(app) as client:
        response = client.post(
            "/api/autonomous/run-once",
            json={
                "datasource": "prometheus",
                "backend": "grafana-stack",
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["capacity"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 1, "max_parallel_jobs": 10},
                "dry_run": True,
            },
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["planned_jobs"] == 1
    assert payload["budget_limited_jobs"] == 2
    assert payload["budget_excluded_metrics_count"] == 2
    assert len(payload["budget_excluded_metrics"]) == 2
    summary = payload["summary"]
    assert summary["budget_limited_jobs"] == 2
    assert summary["budget_excluded_metrics_count"] == 2
    assert len(summary["budget_excluded_metrics"]) == 2
    assert any("Execution budget limited" in w and "Every run is independent" in w for w in payload["warnings"])


def test_policy_runs_api_surfaces_budget_coverage() -> None:
    metrics = [
        metric("cpu_usage", "checkout"),
        metric("memory_usage", "payments"),
        metric("container_memory_working_set_bytes", "shipping"),
    ]
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeMetadataProvider(metrics)
    with TestClient(app) as client:
        run_res = client.post(
            "/api/autonomous/run-once",
            json={
                "datasource": "prometheus",
                "backend": "grafana-stack",
                "scope": {"all_services": True, "all_namespaces": True},
                "monitoring_categories": ["capacity"],
                "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 1, "max_parallel_jobs": 10},
                "dry_run": True,
            },
        )
        assert run_res.status_code == 200
        run_id = run_res.json()["policy_run_id"]

        list_res = client.get("/api/autonomous/policy-runs")
        assert list_res.status_code == 200
        runs = list_res.json()
        matching = [r for r in runs if r["id"] == run_id]
        assert len(matching) == 1
        assert matching[0]["budget_limited_jobs"] == 2
        assert matching[0]["budget_excluded_metrics_count"] == 2
        assert len(matching[0]["budget_excluded_metrics"]) == 2

        get_res = client.get(f"/api/autonomous/policy-runs/{run_id}")
        assert get_res.status_code == 200
        run_dict = get_res.json()
        assert run_dict["budget_limited_jobs"] == 2
        assert run_dict["budget_excluded_metrics_count"] == 2
        assert len(run_dict["budget_excluded_metrics"]) == 2




def test_run_counts_add_up_with_excluded_metrics_counted_apart(monkeypatch) -> None:
    # QA-23: a run read "planned 4, executed 4, skipped 3": metrics screened out before planning
    # were added to skipped_jobs, so executed + skipped + failed came out above planned.
    monkeypatch.setattr(autonomous_execution, "MetricAnalysisExecutor", FakeMetricAnalysisExecutor)
    app = create_app("sqlite+pysqlite:///:memory:")
    app.dependency_overrides[get_prometheus_query_service] = lambda: FakeMetadataProvider([metric("cpu_usage", "checkout"), metric("request_latency_p95", "checkout")])
    body = {
        "scope": {"all_services": True, "all_namespaces": True},
        "monitoring_categories": ["capacity"],
        "execution": {"interval": "10m", "analysis_window": "24h", "max_metrics_per_run": 500, "max_parallel_jobs": 20},
    }
    with TestClient(app) as client:
        run = client.post("/api/autonomous/run-once", json=body).json()
        policy_run = client.get(f"/api/autonomous/policy-runs/{run['policy_run_id']}").json()
        dry_run = client.post("/api/autonomous/run-once", json={**body, "dry_run": True}).json()

    assert (run["planned_jobs"], run["executed_jobs"], run["skipped_jobs"], run["failed_jobs"]) == (1, 1, 0, 0)
    assert run["excluded_jobs"] == 1
    assert run["summary"]["jobs_excluded"] == 1
    assert policy_run["jobs_skipped"] == 0
    assert (dry_run["planned_jobs"], dry_run["skipped_jobs"], dry_run["excluded_jobs"]) == (1, 1, 1)
    assert dry_run["summary"]["jobs_skipped"] == 1
