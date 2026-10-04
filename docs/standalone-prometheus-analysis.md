# Standalone Prometheus Analysis

Ops Signals supports two Prometheus analysis flows.

## Standalone Direct Prometheus

Flow:

```text
Standalone UI
-> Ops Signals backend
-> Prometheus HTTP API /api/v1/query_range
-> normalized time-series samples
-> existing analyzer pipeline
-> signals and findings
```

Use this from the standalone app at `/validate-data` by selecting the `Prometheus`
tab.

Backend endpoints:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/prometheus/connections` | Returns configured Prometheus profiles without secrets. |
| `POST /api/prometheus/test-connection` | Checks the configured Prometheus connection. |
| `POST /api/prometheus/preview` | Runs a bounded `query_range` and returns sample metadata plus a bounded preview. |
| `POST /api/analysis/prometheus` | Runs direct Prometheus analysis through the existing analyzer pipeline. |

Configuration:

```bash
OPS_SIGNALS_PROMETHEUS_URL=http://prometheus:9090
OPS_SIGNALS_PROMETHEUS_BEARER_TOKEN=
OPS_SIGNALS_PROMETHEUS_USERNAME=
OPS_SIGNALS_PROMETHEUS_PASSWORD=
OPS_SIGNALS_PROMETHEUS_VERIFY_TLS=true
OPS_SIGNALS_PROMETHEUS_TIMEOUT_SECONDS=30
OPS_SIGNALS_PROMETHEUS_HEADERS=
OPS_SIGNALS_PROMETHEUS_MAX_WINDOW_DAYS=30
OPS_SIGNALS_PROMETHEUS_MAX_SERIES=20
OPS_SIGNALS_PROMETHEUS_MAX_SAMPLES_PER_SERIES=10000
OPS_SIGNALS_PROMETHEUS_MAX_TOTAL_SAMPLES=100000
OPS_SIGNALS_PROMETHEUS_MIN_STEP_SECONDS=1
OPS_SIGNALS_PROMETHEUS_MAX_STEP_SECONDS=86400
OPS_SIGNALS_PROMETHEUS_CLUSTER_LABEL=cluster
OPS_SIGNALS_PROMETHEUS_REPLICA_LABELS=__replica__,prometheus_replica
```

The last two matter for Mimir, Thanos and other multi-source backends - see
[below](#mimir-thanos-and-other-multi-source-backends).

Secrets are never returned to the browser. Connection profiles are environment
based in this first release; durable stored profiles would require a separate
schema and security review.

Example preview request:

```json
{
  "connection_id": "default",
  "query": "container_cpu_usage_seconds_total{service=\"checkout\"}",
  "start": "2026-07-25T14:00:00Z",
  "end": "2026-07-26T14:00:00Z",
  "step": "5m"
}
```

Example direct analysis request:

```json
{
  "connection_id": "default",
  "query": "container_cpu_usage_seconds_total{service=\"checkout\"}",
  "service": "checkout",
  "metric": "cpu_usage",
  "start": "2026-07-25T14:00:00Z",
  "end": "2026-07-26T14:00:00Z",
  "step": "5m",
  "analyzer": "ruptures",
  "execution_mode": "persist"
}
```

Use `"analyzer": "all"` or `"analyzer": null` to let the analyzer router choose
recommended analyzers. Supplying a concrete analyzer ID enables manual override
for that analyzer.

Time windows are resolved to explicit UTC `start` and `end` timestamps by the UI
before the backend queries Prometheus. The backend validates that `start < end`,
the requested window is within configured bounds, and the requested step will not
exceed sample limits.

The analyzer router requires at least 30 valid samples. For a `5m` step, use a
window of at least 3 hours; `6h` or `24h` is recommended for the lab scenarios.
The standalone UI estimates sample count and disables `Run Analysis` when the
selected range is too short.

For the first release, analysis requires a single returned series. If Prometheus
returns multiple series, refine the label filters before running analysis.

## CSV Upload

Flow:

```text
Standalone UI
-> CSV upload
-> normalization
-> analyzer dry-run or persisted analysis
-> signals and findings
```

The CSV tab on `/validate-data` keeps the existing CSV file selector, provider
mapping, analyzer selector, service, metric, interval, and validation behavior.

## Grafana Datasource-Based Prometheus

Flow:

```text
Grafana datasource
-> Prometheus
-> Grafana frame samples
-> Ops Signals backend /api/ingestion/prometheus-run
```

The Grafana plugin continues to query Prometheus through Grafana datasource APIs.
It sends samples to `POST /api/ingestion/prometheus-run`. The standalone direct
Prometheus endpoints do not replace or modify this contract.

## Mimir, Thanos and Other Multi-Source Backends

Ops Signals reads from Prometheus-compatible backends such as Grafana Mimir,
Thanos and VictoriaMetrics. For a Mimir tenant, pass the tenant header:

```bash
OPS_SIGNALS_PROMETHEUS_HEADERS=X-Scope-OrgID:my-tenant
```

### Several clusters behind one endpoint

These backends often hold data from many Prometheus servers, told apart only by
an external label such as `cluster`. Ops Signals treats series that differ by
that label as separate series:

- **Autonomous analysis** plans one job per cluster. The same service in `eu`
  and `us` becomes two queries, each with a `cluster="…"` matcher and
  `by (service, cluster)`, so clusters are never summed together. The Configure
  panel shows a **Clusters** picker when Prometheus reports more than one value,
  to analyse all clusters or only some.
- **Findings** carry the cluster. Cards and the details drawer show it
  (`checkout · latency_p95 · eu`), the drawer chart shows only that cluster, and
  the Findings page has a cluster filter when findings span several clusters.
  `GET /api/findings?cluster=eu` filters the same way.
- **CSV uploads** with a `cluster` column are split the same way.
- **Alerts** from one cluster never reuse a finding from another cluster.

The label defaults to `cluster`. Set `OPS_SIGNALS_PROMETHEUS_CLUSTER_LABEL` if
yours is different (e.g. `k8s_cluster`), or to `none` to turn this off. A
policy's scope can also set its own `cluster_label`. Data without the label is
analysed exactly as before.

### HA replica pairs

An HA Prometheus pair sends each series twice, differing only by a replica
label. Ops Signals keeps one copy:

- Autonomous queries wrap the series in `max without (<replica labels>) (…)`
  before aggregating, so sums aren't doubled. This is only added when the
  discovered series actually carry a replica label.
- Direct analysis, previews and alert analysis drop the duplicate copies (the
  one with the most samples is kept) and return a warning saying how many were
  dropped. An HA pair no longer fails with "the query returned 2 series".

Replica labels default to `__replica__,prometheus_replica`. Thanos setups that
use a plain `replica` label should set
`OPS_SIGNALS_PROMETHEUS_REPLICA_LABELS=replica` (comma-separated; `none` turns
it off). Deduplicating in the backend too (Mimir's HA tracker, Thanos
`--query.replica-label`) is still a good idea.

### Known limitations

- **One tenant per instance.** Only one connection is supported. To analyze
  several tenants, run one Ops Signals backend per tenant.
- **Hand-written PromQL that aggregates away the cluster** (e.g.
  `sum by (service) (…)` in direct analysis) still adds clusters together;
  keep `cluster` in the `by (…)` or add a `cluster="…"` matcher.
- **Behavior findings** (cross-metric rules) look at one analysis run as a
  whole. Autonomous runs hold one series each, so this only matters for a CSV
  upload that mixes clusters.

To try all of this without a real Mimir, see
[Testing Multi-Cluster Mimir Locally](testing-multicluster-locally.md).

Multiple tenants with a connection picker are tracked in the [roadmap](roadmap.md).

## Troubleshooting

| Symptom | Meaning |
| --- | --- |
| `Prometheus is not configured` | Set `OPS_SIGNALS_PROMETHEUS_URL` and restart the backend. |
| `Prometheus request timed out` | Increase timeout or reduce the query window/sample volume. |
| `query returned N series` | Add label filters or use a more specific PromQL query. |
| `no samples` | The query worked, but no samples exist in the selected time range. |
| `non-numeric sample value` | The query did not return numeric range-vector values suitable for analyzers. |
| `Needs at least 30 valid samples` | Increase the time window or reduce the step. |
| `0 signals and 0 findings` | Analysis ran, but no executed analyzer crossed its signal threshold. Check router decisions and executed analyzers in the UI. |

Lab service labels use hyphens, for example `ruptures-lab`, `trend-lab`, and
`spike-lab`. A query such as `cpu_usage{service="ruptures_lab"}` will not match
the lab data if Prometheus labels use `ruptures-lab`.
