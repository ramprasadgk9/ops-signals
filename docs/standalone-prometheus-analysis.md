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
```

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

Known limitations:

- **One tenant per instance.** Only one connection is supported. To analyze
  several tenants, run one Ops Signals backend per tenant.
- **Series from different clusters are not told apart.** These backends often
  hold data from many Prometheus servers, labelled only by an external label
  such as `cluster`. Autonomous analysis scopes by service, namespace and
  environment, so the same service in two clusters can be merged into one
  series and give misleading findings. Until this is supported, narrow the
  scope to one cluster: in the Configure panel, set **Environment label** to
  `cluster` (or your external label) and pick a single value. For direct
  analysis, add `cluster="…"` to the PromQL query.
- **HA replicas are not deduplicated.** If your backend keeps both copies of an
  HA Prometheus pair (labels such as `__replica__` or `prometheus_replica`),
  enable deduplication in the backend (Mimir's HA tracker, Thanos
  `--query.replica-label`) or filter to one replica.

Planned support is tracked in the [roadmap](roadmap.md).

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
