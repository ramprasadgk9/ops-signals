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
| `GET /api/prometheus/connections` | Lists the configured connections (id, name, URL without credentials, whether it is the default, alert `match_labels`) - never tokens or passwords. |
| `POST /api/prometheus/test-connection` | Checks the connection named by `connection_id`. |
| `GET /api/prometheus/recording-rules` | Lists the connection's recording rules (name, query, group, how often it runs, last-run health, the metrics it reads), from `GET /api/v1/rules?type=record`. Cached for a minute; a server or Mimir tenant without rules gives an empty list. |
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

### What is a "Recording rule" in the Metrics list?

A recording rule is a query Prometheus runs on a schedule (for example every 15s)
and saves under a new metric name. `service:error_rate:percent` can be the saved
result of `100 * avg by (service, env) (error_rate)`. The name looks like any
other metric, so New Analysis tags it **Recording rule** in the Metrics list, with
the rule's group (the name of the set of rules it belongs to in the rules file).

Pick one and a note under the PromQL box shows the rule's saved query, how often
Prometheus runs it, the metrics it reads, and whether its last run failed.
Analysis reads the points Prometheus already saved; it doesn't run the query
again. The finding's details show the same information under **How this was
measured**. That is the rule as it is now: if someone changed it since the run,
older points used the old query.

Two things to know:

- **Short history.** A rule's series starts when the rule was added; Prometheus
  doesn't fill in earlier points. A rule added an hour ago has an hour of data,
  so pick a window and step that give at least 30 points.
- **No service label.** A rule that adds up every service, such as
  `100 * avg(error_rate)`, saves one result for all services, without a
  `service` label. Every finding is saved under one service, so such a rule can
  be previewed but not analyzed: the note says so and **Run Analysis** stays off.
  To analyze it per service, the rule has to keep the label, for example
  `100 * avg by (service) (error_rate)`. In the Grafana plugin, where the metric
  list follows the picked service, a line under the list names the rules it
  hides for this reason.

**Run Analysis** also needs a **Service** for any metric, recording rule or
not: the finding is saved under it. Preview Data works without one.

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

### What should my CSV file look like?

One row per sample, with a `timestamp` (ISO time, UTC) and a numeric `value`. `metric_name`,
`service` and `env` columns are optional: without them, type the metric and service in the form.

```text
timestamp,metric_name,value,service,env
2026-07-30T00:00:00Z,cpu_usage,0.8242,sample-inventory,demo
2026-07-30T00:05:00Z,cpu_usage,0.8058,sample-inventory,demo
```

To see a whole file, open **New Analysis → CSV Upload**: the **Sample files** box at the top has
four files (a sudden jump, a slow climb, short spikes and a repeating pattern), each with
**Download CSV** and its first rows shown. Each has 120 rows, one every 5 minutes. They are also at
`GET /api/samples` (the list) and `GET /api/samples/<file>.csv` (one file). In the demo, **Analyze
it** analyzes one in a click.

## Grafana Datasource-Based Prometheus

Flow:

```text
Grafana datasource
-> Prometheus
-> Grafana frame samples
-> Ops Signals backend /api/ingestion/prometheus-run
```

By default the Grafana plugin's Interactive Analysis queries Prometheus through
Grafana datasource APIs and sends the samples to `POST /api/ingestion/prometheus-run`.
That path has no cluster choice, doesn't tag findings with a cluster, and doesn't
drop HA replica copies. With named connections configured, the plugin can instead
**Query through: Ops Signals connection**, which uses `POST /api/analysis/prometheus`
like the web UI (see [In the web UI and the Grafana plugin](#in-the-web-ui-and-the-grafana-plugin)).

## Mimir, Thanos and Other Multi-Source Backends

Yes, Ops Signals works with Grafana Mimir, Thanos, VictoriaMetrics and other
Prometheus-compatible backends, including several tenants and several clusters
behind one endpoint: each cluster is analysed on its own and HA replica copies
count once. For a single Mimir tenant, pass the tenant header:

```bash
OPS_SIGNALS_PROMETHEUS_HEADERS=X-Scope-OrgID:my-tenant
```

### Several tenants: named connections

To read from more than one tenant (or more than one Prometheus), list them in a
connections file and point `OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE` at it
(YAML, or JSON when the name ends in `.json`):

```yaml
default: team-a          # optional; the first connection otherwise
connections:
  - id: team-a
    name: Mimir team A
    base_url: https://mimir.example.com/prometheus
    bearer_token: ${MIMIR_TEAM_A_TOKEN}
    headers:
      X-Scope-OrgID: team-a
    match_labels:
      tenant: team-a
  - id: team-b
    name: Mimir team B
    base_url: https://mimir.example.com/prometheus
    bearer_token: ${MIMIR_TEAM_B_TOKEN}
    headers:
      X-Scope-OrgID: team-b
    match_labels:
      tenant: team-b
    cluster_label: k8s_cluster   # any per-connection setting below can differ
```

- Each connection takes the same settings as the `OPS_SIGNALS_PROMETHEUS_*`
  variables: `base_url`, `bearer_token`, `username`, `password`, `headers`,
  `verify_tls`, `timeout_seconds`, the `max_*`/`*_step_seconds` limits,
  `cluster_label` and `replica_labels`.
- `grafana_datasources` (file only) lists the Grafana datasources, by uid or
  name, that read the connection. Metric Usage uses it to tell which tenant a
  panel shows; without it a datasource belongs to the connections with the
  same URL. See [Metric Usage](metric-usage.md).
- **Secrets stay out of the file.** `bearer_token`, `username`, `password` and
  header values may use `${ENV_VAR}`; nothing else is expanded. A reference to
  an unset variable stops startup with an error naming it.
- The file is checked at startup: a duplicate id, an unknown `default`, an
  empty list or an unreadable file stops the backend instead of failing later.
  Edits to the file are picked up on the next request, without a restart; an
  edit that breaks the file makes Prometheus requests fail with that error
  until it is fixed.
- Without the file, the `OPS_SIGNALS_PROMETHEUS_*` variables describe one
  connection with id `default`, exactly as before.
- A commented starting point is in
  [`examples/prometheus-connections.yaml`](../examples/prometheus-connections.yaml).
  With Docker Compose, add `docker-compose.connections.yml`
  ([how](release-packaging.md#several-mimir-tenants-with-docker-compose)); with
  Helm, set `prometheusConnections`
  ([how](release-packaging.md#several-mimir-tenants-with-helm)).

Every API call that queries Prometheus takes a `connection_id` (query string or
JSON body). It defaults to the default connection, and `default` always means
the default connection, so existing clients keep working. An unknown id is a
404 - Ops Signals never quietly queries a different tenant.

- **Configure panel and Validate Data** show a **Prometheus connection** picker
  when there is more than one connection. Switching it clears the selected
  services, namespaces and clusters, since another tenant has its own.
- **Autonomous policies** remember their connection (`connection_id`). A
  scheduled run queries only that connection; if it has been removed from the
  file, the run fails instead of falling back to the default.
- **Alerts** are analysed on the first connection whose `match_labels` all
  appear on the alert (e.g. `tenant="team-b"`), and on the default connection
  when none match. An alert never reuses a finding produced from another
  connection, even when the cluster names are the same.
- **Findings** carry `connection_id` (`null` for CSV and OTLP), and cards and
  the details drawer name the connection when there is more than one.
- **Integrations** status lists each connection and whether it answers.

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
- **Validate Data** shows a **Cluster** field when the chosen service and
  metric exist in more than one cluster, and **Run Analysis** waits until you
  pick one; the matcher is added to the query for you. With one cluster or none,
  nothing changes. Hand-written PromQL that matches several clusters gets an
  error naming them and the query that picks one.
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

### One series per pod

Most Kubernetes metrics have one series per pod (or per `instance` on plain
machines). The analysis reads one line, so New Analysis combines them the way
scheduled runs do, with the same per-metric choice from
`config/prometheus_metric_knowledge.yaml`: latency and memory are averaged,
request and error counts are added up, health checks such as `up` take the
lowest pod. A metric no rule knows is averaged, unless its name says it counts
something (`_per_second`, `_rps`, `_qps`, `_total`, `_count`): then the pods are
added up, so `http_requests_per_second` reads as the service's traffic. That
only picks how New Analysis combines pods; scheduled runs still skip metrics
no rule knows.

- **Simple mode, Run Analysis** combines the pods without asking. The result
  says how ("Analyzed as one line: the average of 4 pods") and shows the query
  it ran, such as `avg by (service) (request_latency_p95{service="search-svc"})`.
- **Preview Data** draws every pod as a thin line and the combined line in dark.
  A **Pods** box under the form lets you pick another way (highest, added up,
  average, lowest) or one pod alone. If one pod behaves differently from the
  rest, the box names it ("search-svc-2 is behaving differently from the other
  3 pods…") with **Analyze only search-svc-2**.
- **Findings** from a combined run say which pods the change came from, using
  the same drill-down as scheduled runs (on for these runs even when
  `OPS_SIGNALS_DRILLDOWN_ENABLED` is off).
- **Advanced PromQL** is run exactly as written. If it returns one series per
  pod, the error stays, and the Pods box offers **Combine** buttons that put a
  wrapped query (`avg by (…) (your query)`) in the box for you to check and
  run. A one-pod button is offered only for a plain selector.

More pods than `OPS_SIGNALS_PROMETHEUS_MAX_SERIES` (20 by default) are still
combined when Run Analysis combines them: the backend reads only the series'
labels (about 50 points each, up to 2,000 series), checks that they differ only
by pod, and then reads the combined line alone. Preview still stops at the
limit, there is no odd pod named, and findings don't say which pod the change
came from, because that breakdown would need every pod's line.

Series are combined only when the pod (or instance) label has one value per
series. If they also differ by something else, such as a status code, or by
cluster, the run stops with the message naming that label, as before. The
labels tried are the drill-down labels: `pod`, `pod_name`,
`kubernetes_pod_name`, `instance` and `host` by default
(`OPS_SIGNALS_DRILLDOWN_LABELS` to change them). The API takes `"combine": "auto"` (or `max`,
`sum`, `avg`, `min`) on `POST /api/analysis/prometheus`; without it a query is
analysed exactly as written.

### Known limitations

- **Hand-written PromQL that aggregates away the cluster** (e.g.
  `sum by (service) (…)` in direct analysis) still adds clusters together;
  keep `cluster` in the `by (…)` or add a `cluster="…"` matcher.
- **Behavior findings** (cross-metric rules) look at one analysis run as a
  whole. Autonomous runs hold one series each, so this only matters for a CSV
  upload that mixes clusters.

### In the web UI and the Grafana plugin

Both UIs use the same backend endpoints, so tenants, clusters and replica pairs
are handled the same way. They differ only in what each form lets you set.

| | Web UI | Grafana plugin |
|---|---|---|
| **Autonomous: Prometheus connection** (one per tenant) | Configure, with the cluster list per connection | Configure → Analysis Scope, with **Test** |
| **Autonomous: clusters** | Shown when there is a choice, or a schedule is narrowed to clusters | Always shown: the choice, the only cluster, or "No clusters" |
| **One metric: connection and cluster** | Validate Data → Prometheus | Interactive Analysis → **Query through: Ops Signals connection** |
| Cluster asked for when the series is in several; run waits for it | ✅ | ✅ |
| HA replica copies dropped, with a warning | ✅ | ✅ |
| Series per pod combined into one line, with the odd pod named | ✅ with a Pods box after Preview | ✅ in Metric mode with either source, noted on the result |
| More than 20 pods combined (no odd pod, no per-pod breakdown) | ✅ on Run Analysis | ✅ in Metric mode with either source |
| PromQL with one series per pod: **Combine** buttons that put the combined query in the box | ✅ Advanced mode | ✅ PromQL mode, either source |
| "This query matched N series… add `pod="…"`" when the series differ by more than the pod | ✅ | ✅ |
| Findings labelled with cluster (and connection, when there are several) | Findings page, finding drawer | Symptom rows, finding panel, case drawer |
| Filter by cluster | Findings page | Autonomous overview chips |
| Query through a Grafana data source instead | — | ✅ the default; no cluster handling |
| Several metrics in one run, analyzer and step choice, query preview | ✅ | — one metric, all analyzers, step from the time range |

Switching connection clears the previous preview in both, and the preview says
which connection it is for. Cases keep the cluster and connection of the finding
they were opened from (cases opened before this was added don't have them).

To try all of this without a real Mimir, see
[Testing Multi-Cluster Mimir Locally](testing-multicluster-locally.md).

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
