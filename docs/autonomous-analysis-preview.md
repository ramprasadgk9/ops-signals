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

### Push-Down Scoping and Anti-Starvation Discovery

To prevent cluster-wide cardinality explosion and alphabetical metric starvation:

- **Push-Down Scoped Discovery**: When a policy is scoped to a specific service or namespace, the discovery engine pushes the selector directly down into Prometheus (`GET /api/v1/series?match[]={...}`) in a single query. Discovery volume scales with the policy's own scope rather than cluster cardinality.
- **Fair Allocation & Dynamic Quota**: When running unscoped (cluster-wide), series discovery allocates budget across all discovered metric names using dynamic quota (`max(1, limit // len(metric_names))`) and round-robin allocation. Early-alphabet or high-cardinality metrics (e.g. `apiserver_*`) cannot monopolize the series cap and starve later metrics (e.g. `zebra_*`).
- **Per-Metric Budgeting**: Both scoped and unscoped discovery cap individual metrics up to `max_series_per_metric` and round-robin allocate series to preserve multi-dimensional representation without pod hash monopolization.
- **Deterministic Sampling**: Results are deterministically sorted by metric identity and labels prior to sampling to guarantee reproducible plan generation across identical cluster states.

## Query Planning

Each selected metric is converted into a planned single-metric analysis job. The planner returns the PromQL, transformation, aggregation, category, concept, confidence, and the future `AnalysisRequest` payload.

Examples:

- Gauge CPU: `avg by (service) (cpu_usage{service="payments"})`
- Counter request rate: `sum by (service) (rate(http_requests_total{service="payments"}[5m]))`
- Histogram latency: `histogram_quantile(0.95, sum by (le, service) (rate(http_request_duration_seconds_bucket{service="payments"}[5m])))`

The planner deduplicates lower-ranked metrics that represent the same service, category, and primary concept, then applies the max-metrics budget.

## Preview Response

The response contains:

- `scope_summary`: resolved services, namespaces, environment, label mapping, selector, `series_discovered`, `series_available`, `truncated`, `starved_metrics_count`, `starved_metrics`, `budget_limited_jobs`, `budget_excluded_metrics_count`, and `budget_excluded_metrics`
- `monitoring_summary`: selected categories and expanded concepts
- `metrics_discovered`, `metrics_classified`, `metrics_selected`, `planned_jobs`, and `budget_limited_jobs`
- discovery coverage & truncation metrics:
  - `series_discovered`: total series retained after fair sampling
  - `series_available`: total series available in Prometheus matching the scope
  - `truncated`: `true` if any metric was starved or the discovery cap was reached
  - `starved_metrics_count`: count of metric names that yielded 0 series due to cap truncation
  - `starved_metrics`: list of metric names that received 0 series
- execution budget coverage metrics:
  - `budget_limited_jobs`: count of selected jobs excluded by `max_metrics_per_run`
  - `budget_excluded_metrics_count`: count of distinct metric names excluded by execution budget
  - `budget_excluded_metrics`: list of distinct metric names excluded by execution budget
- per-metric rows with status, reason, PromQL, aggregation, confidence, and planned request details

Excluded rows remain visible so users can validate why a metric was skipped.

## Run Once

`POST /api/autonomous/run-once` rebuilds the preview plan, executes planned rows up to the selected budget, queries Prometheus for the requested analysis window, and sends each one-series result through the autonomous `MetricAnalysisExecutor`.

Run-once behavior:

- executes only rows marked `planned`
- requires each planned PromQL query to return exactly one logical series
- persists normal analysis runs, signals, findings, and behavior findings through shared storage
- surfaces execution budget coverage (`budget_limited_jobs`, `budget_excluded_metrics_count`, `budget_excluded_metrics`) in the response root and `summary` object
- returns per-job status, sample count, signal count, finding count, behavior finding count, warnings, and errors
- does not create a persistent autonomous policy or background schedule

### Execution Budget & Independent Run Model

Execution respects `max_metrics_per_run` (default 500, max 5,000). When classification selects more metrics than the configured budget:
- Top-ranked metrics up to `max_metrics_per_run` are executed.
- Excluded metrics are recorded with `exclusion_reason="budget_limit"` and surfaced in `budget_excluded_metrics`.
- **Every run is independent**: budget-excluded metrics are not deferred, queued, or carried over to future runs. To achieve broader coverage, operators must increase `max_metrics_per_run` or narrow scope using service and namespace filters.

### Execution Concurrency (`max_parallel_jobs`)

`max_parallel_jobs` is an execution policy setting (default 20, max 200). Execution currently runs sequentially in a single transaction loop to preserve database transactional safety and deterministic order across SQLite and PostgreSQL storage. The `max_parallel_jobs` field is preserved in run configuration and reserved for future worker concurrency.

For local mock Prometheus data, prefer `All environments`, service `ruptures-lab`, category `Capacity`, and a `6h` analysis window. A `24h` window can include sparse sample gaps and may be rejected by the existing time-series validator.

## Results Dashboard

The web UI's Autonomous Analysis Configure page renders results inline, in place, right after a
run completes - it doesn't just show a status banner and leave you to go find the results
elsewhere. The same `AutonomousRunResponse` returned by `run-once` drives a dashboard showing
discovery/selection counts, execution summary, top findings by importance, behavior distribution,
execution history, and recent cases, reusing the query keys the Overview page already invalidates
so both stay in sync.

## Non-Goals

This implementation intentionally does not:

- change interactive analysis behavior
- change analyzer routing or analyzer execution
- create scheduler state
- generate raw labelset jobs for every time series
- expose arbitrary PromQL editing in the UI

Scheduler execution can consume the returned `planned_request` objects later without changing the metric planning contract.
