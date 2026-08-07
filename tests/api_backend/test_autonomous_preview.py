from fastapi.testclient import TestClient

from backend.app.api.autonomous import get_prometheus_query_service
from backend.app.autonomous.schemas import AnalysisScope, CustomMetricConstraints, DiscoveredMetric, ExecutionPolicy, MetricConcept, MonitoringCategory
from backend.app.autonomous.services import MetricClassificationService, MetricDiscoveryService, MetricPlanBuilder, build_label_matcher, build_scope_selector, validate_label_name
from backend.app.main import create_app


class FakeMetadataProvider:
    def __init__(self, metrics: list[DiscoveredMetric]):
        self.metrics = metrics

    def discover_metric_metadata(self, **kwargs):
        return list(self.metrics)

    def label_values(self, label: str):
        values = sorted({metric.labels[label] for metric in self.metrics if label in metric.labels})
        return values


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


def test_selected_service_filtering() -> None:
    plan = build_plan([metric("cpu_usage", "checkout"), metric("memory_usage", "payments")], AnalysisScope(all_services=False, services=["payments"]))
    assert plan.total_metrics_discovered == 1
    assert plan.items[0].service == "payments"


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


def test_multi_category_classification() -> None:
    plan = build_plan([metric("container_cpu_usage_seconds_total")], categories=[MonitoringCategory.capacity, MonitoringCategory.infrastructure])
    assert plan.items[0].planned is True
    assert plan.items[0].category in {MonitoringCategory.capacity, MonitoringCategory.infrastructure}


def test_budget_enforcement() -> None:
    plan = build_plan([metric("cpu_usage", "a"), metric("memory_usage", "b")], categories=[MonitoringCategory.capacity], max_metrics=1)
    assert plan.planned_jobs == 1
    assert plan.budget_limited_jobs == 1


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
    assert payload["planned_jobs"] == 1
    assert payload["executed_jobs"] == 0
    assert payload["results"][0]["status"] == "skipped"


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
