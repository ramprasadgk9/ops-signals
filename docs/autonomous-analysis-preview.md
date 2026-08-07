# Autonomous Analysis Metric Planning

Autonomous analysis now previews concrete Prometheus metric jobs from three inputs:

- monitoring intent: selected categories such as performance, capacity, availability, and custom
- analysis scope: environment, service, namespace, and the Prometheus label names that identify them
- execution policy: interval, analysis window, max metrics per run, and max parallel jobs

This capability supports previewing a metric plan and running that plan once on demand. It does not start a repeating scheduler.

## Intent Expansion

The UI category selection is expanded through `config/autonomous_metric_taxonomy.yaml`.

For example, selecting `performance` expands into concepts such as `latency`, `throughput`, `request_rate`, and `processing_duration`. The taxonomy describes operational intent; it does not select analyzers directly.

## Prometheus Knowledge

Metric classification uses `config/prometheus_metric_knowledge.yaml`.

The knowledge file provides:

- excluded metadata metrics such as `_info` and `_created`
- exact known metric mappings such as `cpu_usage`, `memory_usage`, `up`, and `request_latency_p95`
- regex pattern mappings such as latency, request counters, error rates, retries, Kafka lag, and Kubernetes metrics
- metric type hints and query strategies

Classification is layered:

1. custom explicit metrics
2. custom include patterns when the `custom` category is selected
3. exact known metric mappings
4. configured name patterns
5. exclusions, required labels, and selected-category filtering

## Scope Resolution

`POST /api/autonomous/preview` discovers Prometheus metadata and resolves the selected scope into safe Prometheus label matchers.

Example scope:

```json
{
  "environment": "production",
  "services": ["payments"],
  "namespaces": ["commerce"],
  "service_label": "service",
  "namespace_label": "namespace",
  "environment_label": "env"
}
```

Resolved selector:

```promql
{env="production",service="payments",namespace="commerce"}
```

If all services or all namespaces are selected, that label matcher is omitted.

## Query Planning

Each selected metric is converted into a planned single-metric analysis job. The planner returns the PromQL, transformation, aggregation, category, concept, confidence, and the future `AnalysisRequest` payload.

Examples:

- Gauge CPU: `avg by (service) (cpu_usage{service="payments"})`
- Counter request rate: `sum by (service) (rate(http_requests_total{service="payments"}[5m]))`
- Histogram latency: `histogram_quantile(0.95, sum by (le, service) (rate(http_request_duration_seconds_bucket{service="payments"}[5m])))`

The planner deduplicates lower-ranked metrics that represent the same service, category, and primary concept, then applies the max-metrics budget.

## Preview Response

The response contains:

- `scope_summary`: resolved services, namespaces, environment, label mapping, and selector
- `monitoring_summary`: selected categories and expanded concepts
- `metrics_discovered`, `metrics_classified`, `metrics_selected`, `planned_jobs`, and `budget_limited_jobs`
- per-metric rows with status, reason, PromQL, aggregation, confidence, and planned request details

Excluded rows remain visible so users can validate why a metric was skipped.

## Run Once

`POST /api/autonomous/run-once` rebuilds the preview plan, executes planned rows up to the selected budget, queries Prometheus for the requested analysis window, and sends each one-series result through the existing `SignalPipeline`.

Run-once behavior:

- executes only rows marked `planned`
- requires each planned PromQL query to return exactly one logical series
- persists normal analysis runs, signals, findings, behavior findings, and cases through existing storage
- returns per-job status, sample count, signal count, finding count, behavior finding count, warnings, and errors
- does not create a persistent autonomous policy or background schedule

For local mock Prometheus data, prefer `All environments`, service `ruptures-lab`, category `Capacity`, and a `6h` analysis window. A `24h` window can include sparse sample gaps and may be rejected by the existing pipeline validator.

## Non-Goals

This implementation intentionally does not:

- change interactive analysis behavior
- change analyzer routing or analyzer execution
- create scheduler state
- generate raw labelset jobs for every time series
- expose arbitrary PromQL editing in the UI

Scheduler execution can consume the returned `planned_request` objects later without changing the metric planning contract.
