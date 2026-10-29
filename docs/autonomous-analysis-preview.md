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

- **Push-Down Scoped Discovery**: When a policy is scoped to a specific service or namespace, the discovery engine pushes the selector directly down into Prometheus (`GET /api/v1/series?match[]={...}&limit=<metadata_limit + 1>`) in a single query. Discovery volume scales with the policy's own scope rather than cluster cardinality. If the scope has more series than `metadata_limit`, discovery uses the per-metric path below instead.
- **Bounded Series Lists**: Every series list is requested with `limit`, one row more than it keeps, so a metric with millions of series (a label with a value per user or request) can't make the answer huge. Without it, Mimir refuses answers over 100 MB and the backend needs about 11x the answer size in memory. When a list comes back cut off, the metrics it never reached are asked for one at a time (`limit=<quota>`), so every metric is still found, and the run's warnings name the metric that filled the list. A server that ignores `limit` sends the whole list, which is handled as before.
- **Fair Allocation & Dynamic Quota**: When running unscoped (cluster-wide), series discovery allocates budget across all discovered metric names using dynamic quota (`max(1, limit // len(metric_names))`) and round-robin allocation. Early-alphabet or high-cardinality metrics (e.g. `apiserver_*`) cannot monopolize the series cap and starve later metrics (e.g. `zebra_*`).
- **Per-Metric Budgeting**: Both scoped and unscoped discovery cap individual metrics up to `max_series_per_metric` and round-robin allocate series to preserve multi-dimensional representation without pod hash monopolization.
- **Deterministic Sampling**: Results are deterministically sorted by metric identity and labels prior to sampling to guarantee reproducible plan generation across identical cluster states.

#### Discovery Order, Step By Step

Given an unscoped policy and `metadata_limit` (the discovery cap, default 5,000), the raw series scan proceeds in this order:

1. **List metric names**: `GET /api/v1/label/__name__/values` returns every metric name, alphabetically sorted.
2. **Size a fair quota up front, before fetching anything**: `quota = min(max_series_per_metric, metadata_limit // <number of metric names>)`. Sizing the quota first is what stops one high-cardinality, alphabetically-early metric (e.g. `apiserver_request_duration_seconds`) from consuming the whole cap before a `z`-prefixed metric is ever queried.
3. **Fetch in chunks of 80 metric names** via `/api/v1/series?match[]=...&limit=<metadata_limit + 1>`, one request per chunk, chunks still walked in alphabetical order. If a chunk's list is cut off, each metric name the list didn't reach is fetched on its own with `limit=<quota>`.
4. **Cap each metric name to its quota** as rows come back, after sorting deterministically by metric/service/namespace/env/labels.
5. **Interleave round-robin, not metric-by-metric, for the final row order**: `metric1[0], metric2[0], metric3[0], ..., metric1[1], metric2[1], ...`. If the cap is ever reached mid-scan, it cuts the *last round* evenly across all metrics rather than dropping an entire alphabetical tail.

Because the quota is sized as `metadata_limit // <metric name count>` before any fetching starts, `quota x <metric name count>` rarely exceeds `metadata_limit`, so in practice every chunk gets processed and `starved_metrics` (metric names with **zero** rows) comes back empty. A metric can still be *partially* sampled - capped at its own quota - without appearing in `starved_metrics`; that list only tracks total exclusion, not per-metric truncation.

When a list was cut off, the total number of series isn't known, so `series_available` is `null`.

**Caveat:** `truncated` is computed as `starved_metrics non-empty OR series_discovered >= metadata_limit`. If Prometheus genuinely has exactly `metadata_limit` series and all of them fit with room to spare under each metric's quota, `truncated` still reports `true` even though nothing was actually dropped - the `>=` check can't distinguish "landed exactly on the ceiling" from "there was more we didn't see."

## Query Planning

Each selected metric is converted into a planned single-metric analysis job. The planner returns the PromQL, transformation, aggregation, category, concept, confidence, and the future `AnalysisRequest` payload.

Examples:

- Gauge CPU: `avg by (service) (cpu_usage{service="payments"})`
- Counter request rate: `sum by (service) (rate(http_requests_total{service="payments"}[5m]))`
- Histogram latency: `histogram_quantile(0.95, sum by (le, service) (rate(http_request_duration_seconds_bucket{service="payments"}[5m])))`

The planner deduplicates lower-ranked metrics that represent the same service, category, and primary concept, then applies the max-metrics budget. Custom metrics (an explicit list or an include pattern) all share the concept `custom`, so they are told apart by metric name: every custom metric gets its own job per service.

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
- stores each point of a series once: a run analyzes its whole window, but saves only the points
  newer than the series' last stored point. A series is one query on one connection, so a
  schedule that looks at the last 24h every 30 minutes adds about 30 minutes of points per run
  instead of another 24h copy. A finding's chart reads the series between the run's start and
  end time, so it still shows the whole window.
- surfaces execution budget coverage (`budget_limited_jobs`, `budget_excluded_metrics_count`, `budget_excluded_metrics`) in the response root and `summary` object
- returns per-job status, sample count, signal count, finding count, behavior finding count, warnings, and errors
- does not create a persistent autonomous policy or background schedule

### Execution Budget & Independent Run Model

Execution respects `max_metrics_per_run` (default 500, max 5,000). When classification selects more metrics than the configured budget:
- Top-ranked metrics up to `max_metrics_per_run` are executed.
- Excluded metrics are recorded with `exclusion_reason="budget_limit"` and surfaced in `budget_excluded_metrics`.
- **Every run is independent**: budget-excluded metrics are not deferred, queued, or carried over to future runs. To achieve broader coverage, operators must increase `max_metrics_per_run` or narrow scope using service and namespace filters.

#### The Discovery Cap and the Execution Budget Are Two Different Limits

`metadata_limit` (discovery, see [above](#discovery-order-step-by-step)) and `max_metrics_per_run` (execution budget) sound similar, and operators sometimes set them to the same number, but they cap two different, sequential populations:

| Stage | Cap | Population it limits |
| --- | --- | --- |
| Discovery | `metadata_limit` | Raw Prometheus **series** pulled off the wire |
| Classification | none (a filter, not a cap) | Discovered series narrowed to ones matching a known exact/pattern rule *and* an enabled monitoring category |
| Planning | `max_metrics_per_run` | Classified, deduplicated, ranked metrics that actually get queried and executed |

**Worked example**: Prometheus has 5,000 series and `metadata_limit = 5,000`. Discovery pulls up to all 5,000 rows, fairly distributed by the round-robin/quota process described above. Those rows then go through `MetricClassificationService`: only rows matching a rule in `config/prometheus_metric_knowledge.yaml` *and* belonging to an enabled monitoring category are `selected` - typically a small fraction of the 5,000, since most raw series (custom app metrics, `_bucket`/`_sum`/`_count` variants, unrecognized names) don't match a known pattern. The selected set is then deduplicated by `(environment, namespace, service, category, concept)` - with the metric name in place of the concept for custom metrics - keeping the highest-ranked row per group, and ranked by:

1. classification confidence (descending)
2. demo-lab priority (internal, for local preview data only)
3. referenced by a recording rule
4. referenced by an alert rule
5. referenced by a dashboard
6. lower series cardinality (tie-breaker)

Setting `max_metrics_per_run = 5,000` almost never actually binds in this scenario, because the selected-and-deduped set is usually far smaller than 5,000 - every selected metric gets planned, and `budget_limited_jobs` comes back `0`. The budget only becomes the real constraint when classification is broad enough (e.g. wide custom include patterns) that the selected set itself approaches the discovery cap - at that point the ranking order above, not discovery's round-robin order, decides which metrics get executed.

### Execution Concurrency (`max_parallel_jobs`)

`max_parallel_jobs` is an execution policy setting (default 20, max 200). Execution currently runs sequentially in a single transaction loop to preserve database transactional safety and deterministic order across SQLite and PostgreSQL storage. The `max_parallel_jobs` field is preserved in run configuration and reserved for future worker concurrency.

For local mock Prometheus data, prefer `All environments`, service `ruptures-lab`, category `Capacity`, and a `6h` analysis window. A `24h` window can include sparse sample gaps and may be rejected by the existing time-series validator.

## Scheduling

A policy can run once on demand or be saved as a recurring schedule (a `Run once` / `Scheduled`
toggle, plus a `Run every` interval) backed by an in-process scheduler. Each policy tracks
`schedule_minutes`, `next_run_at`, `last_run_status`, and `consecutive_failures`, so a failing
schedule surfaces instead of silently going quiet. A saved schedule is what makes analysis
continuous rather than one-off.

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
