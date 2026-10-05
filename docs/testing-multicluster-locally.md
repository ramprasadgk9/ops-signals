# Testing Multi-Cluster Mimir Locally

One command starts a small Grafana Mimir with several Prometheus "clusters" writing into it, so you
can try Ops Signals' multi-cluster handling ([Mimir, Thanos and other multi-source
backends](standalone-prometheus-analysis.md#mimir-thanos-and-other-multi-source-backends)) without a
real Mimir. It runs separately from the usual `docker-compose.yml`, so your normal setup is untouched.

## What you get

```text
metrics-eu ──► prometheus-eu-a (cluster=eu, prometheus_replica=a) ─┐
           └─► prometheus-eu-b (cluster=eu, prometheus_replica=b) ─┤ tenant team-a
metrics-us ──► prometheus-us   (cluster=us)                       ─┼─► Mimir  http://localhost:9009/prometheus
metrics-staging ► prometheus-staging (cluster=staging)            ─┘ tenant team-b
```

| What | Why it's there |
|---|---|
| Clusters `eu` and `us` in tenant `team-a` | The same services (`checkout`, `payments`, `search`) in two clusters, told apart only by the `cluster` label. |
| `eu` is an HA pair | Two Prometheus servers scrape the same target, so Mimir stores every `eu` series twice (`prometheus_replica` a and b). Mimir's own HA dedup is off on purpose, so Ops Signals' replica handling is what gets tested. |
| A recurring incident in `us` only | `checkout` in `us` gets 3x slower for 15 minutes every 8 hours (00:00, 08:00 and 16:00 UTC). `eu` stays healthy, so findings should appear for `us` only. |
| Tenant `team-b` with cluster `staging` | Kept separate from `team-a`, read through its own named connection. |
| 72 hours of history | Written straight into Mimir on the first start, so analyzers have a baseline from the first minute. |

Metrics: `request_latency_p95`, `error_rate`, `cpu_usage` (gauges) and `http_requests_total`
(counter), all with a daily cycle and labels `service`, `env="prod"`, `job`, `instance`, `cluster`.

Needs Docker and about 1 GB of free memory.

## Steps

```bash
./scripts/multicluster.sh up
./scripts/multicluster.sh check
```

`up` starts everything and waits for the history backfill (about a minute the first time). `check`
confirms the clusters, both replica copies, the tenant split, the history and the `us`-only incident.

Then start Ops Signals reading from Mimir instead of your usual Prometheus. Stop your usual
`./scripts/run_all.sh` first (same ports):

```bash
./scripts/multicluster.sh app
```

This runs `run_all.sh` with one named connection per tenant, from
[`dev/multicluster/connections.yaml`](../dev/multicluster/connections.yaml): `team-a` (the default)
and `team-b`, each sending its own `X-Scope-OrgID`. `./scripts/multicluster.sh env` prints the
setting, to put in `.env` instead:

```bash
OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE=<repo>/dev/multicluster/connections.yaml
```

If your `.env` already sets `OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE`, comment that line out -
`run_all.sh` loads `.env` and it would win. (`OPS_SIGNALS_PROMETHEUS_URL` in `.env` doesn't matter:
the connections file replaces it.) Run `./scripts/multicluster.sh check` again: the last
check now goes through the app.

## What to look at in the UI

Open http://localhost:5174.

1. **Autonomous Analysis Configure.** Under Namespaces there is now **All clusters** and a
   **Clusters** picker listing `eu` and `us`. Pick services (e.g. `checkout`) and the Performance
   category, then **Preview**: each metric gets one job per cluster. The `eu` queries are wrapped in
   `max without (prometheus_replica) (…)`, the `us` ones aren't.
2. **Run once**, then **Findings**. Findings are labelled `checkout · request_latency_p95 · us`, the
   latency incident shows up for `us`, and the **Cluster** filter switches between them. The details
   drawer shows the cluster and charts only that cluster.
3. **Validate Data → Prometheus.** Pick service `checkout` and metric `request_latency_p95`. A
   **Cluster** field appears (`eu`, `us`) and **Run Analysis** waits until you choose one; choosing
   adds `cluster="…"` to the query. With `eu`, Mimir returns two copies, Ops Signals keeps one and
   says so in a warning. On `team-b`, or for a series in one cluster, there is no Cluster field. The
   Lab Scenarios chips are hidden here, since those services only exist in `run_all.sh`'s Prometheus.
4. **Two tenants.** The Configure panel and Validate Data have a **Prometheus connection** picker.
   Switch it to `Mimir team-b (staging)`: the cluster list becomes `staging` only, and a preview or
   run queries tenant `team-b`. Findings from it are labelled with the connection name. Alerts with
   `tenant="team-b"` are analysed on `team-b`; alerts without a `tenant` label go to `team-a`.

To see the problem Ops Signals avoids, compare these in a Prometheus UI or with curl:

```bash
curl -s -G -H 'X-Scope-OrgID: team-a' http://localhost:9009/prometheus/api/v1/query --data-urlencode 'query=sum(rate(http_requests_total{cluster="eu",service="checkout"}[10m]))'
curl -s -G -H 'X-Scope-OrgID: team-a' http://localhost:9009/prometheus/api/v1/query --data-urlencode 'query=sum(max without (prometheus_replica) (rate(http_requests_total{cluster="eu",service="checkout"}[10m])))'
```

The first is twice the second: summing both replica copies doubles the traffic.

## Day to day

| Command | Does |
|---|---|
| `./scripts/multicluster.sh status` | Containers, and series and clusters per tenant |
| `./scripts/multicluster.sh logs mimir` | Follow one service's logs (any service name from `status`) |
| `./scripts/multicluster.sh down` | Stop, keep the data. `up` resumes, and live data continues the history. |
| `./scripts/multicluster.sh reset` | Stop and delete everything; the next `up` backfills fresh history |

Leave it running for days to test scheduled policies, findings building up over time and alert
reuse. Mimir keeps 30 days.

If a query fails with `the bucket index is too old (err-mimir-bucket-index-too-old)`, Mimir's
compactor stopped refreshing its list of stored blocks - usually because the machine slept. The
config here tolerates a week of that; if it still happens, `docker compose -f
dev/multicluster/docker-compose.yml restart mimir` rebuilds the index at once (no data is lost).

The Validate Data **Lab Scenarios** (`spike-lab`, `trend-lab`, ...) come from `run_all.sh`'s mock
Prometheus and aren't in Mimir; query `checkout`, `payments` or `search` here instead.

Per-cluster Prometheus UIs, to see exactly what each "cluster" scrapes: eu-a
http://localhost:9191, eu-b http://localhost:9192, us http://localhost:9193, staging
http://localhost:9194.

## Changing the scenario

Everything is in `dev/multicluster/`:

- `docker-compose.yml`: which cluster has an incident (`INCIDENT_SERVICE`, `INCIDENT_EVERY_MINUTES`,
  `INCIDENT_FOR_MINUTES`, `INCIDENT_FACTOR` on `metrics-us`, and the same values on `backfill` so
  the history matches), and how much history (`BACKFILL_HOURS=24 ./scripts/multicluster.sh up` after
  a `reset`).
- `prometheus/*.yml`: each Prometheus's `external_labels` (its cluster and replica) and Mimir tenant.
- `mimir.yaml`: single-process Mimir on local disk. Turning on Mimir's HA tracker here would make
  Mimir drop the `eu` duplicates itself, as many production setups do.
- `cluster_metrics.py`: the services, metrics and their shapes. Values come from the clock alone, so
  the backfilled history and the live data line up.

Run `./scripts/multicluster.sh reset` and `up` after changing anything that affects history.
