# Data sources

How data gets into Ops Signals: Prometheus (pulled), CSV (uploaded), OTLP (pushed), and deploy
events from your CI. Which features each source turns on is in
[What each source turns on](integrations.md#what-each-source-turns-on).

## Prometheus

Connect Ops Signals to an existing Prometheus datasource for direct or autonomous analysis. See
[`standalone-prometheus-analysis.md`](standalone-prometheus-analysis.md).

One Prometheus is set with `OPS_SIGNALS_PROMETHEUS_URL`. For Grafana Mimir with several tenants (or
several Prometheus servers), list them as named connections in a file set by
`OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE` - start from
[`examples/prometheus-connections.yaml`](../examples/prometheus-connections.yaml). The Configure panel and
Validate Data then get a connection picker, each autonomous policy keeps its connection, and alerts
are analysed on the tenant their labels match. Series from several clusters behind one endpoint are
analysed per cluster, and HA replica copies count once. See
[Mimir, Thanos and other multi-source backends](standalone-prometheus-analysis.md#mimir-thanos-and-other-multi-source-backends).

First-time setup in `.env` is in
[Point It at Your Own Prometheus](getting-started.md#point-it-at-your-own-prometheus-optional).

### Switching later

Moving from the bundled Prometheus to your own, or from one Prometheus to several Mimir tenants, is a
change to `.env` and a restart; nothing is reinstalled.

- Policies and findings made before keep working: they belong to the connection `default`, which
  always means the default connection, the first one in the file unless it sets `default:`.
- The connections file is checked at startup: a duplicate id, an unknown `default` or an unset
  `${TOKEN}` stops the backend with an error naming it. Later edits to the file are picked up without
  a restart.
- After the restart, Configure and New Analysis get a connection picker, Integrations lists each
  connection and whether it answers, and alerts go to the connection whose `match_labels` they carry.

## CSV Input

Upload a CSV from **New Analysis**: **Validate Data** previews it, **Analyze and Save** stores the
findings. The columns:

```csv
timestamp,service,metric_name,value,env,host,namespace,pod,unit,metric_type
2026-07-12T14:00:00Z,payments-api,cpu_usage,78.2,prod,ip-10-0-1-5,,payments-7d8c9,percent,gauge
2026-07-12T14:01:00Z,payments-api,cpu_usage,84.6,prod,ip-10-0-1-5,,payments-7d8c9,percent,gauge
```

## OTLP

Prometheus and CSV are both pull/upload - Ops Signals asks for the data. OTLP is the reverse: an
OTel SDK or Collector pushes metrics to Ops Signals. Setup, guardrails and what works with OTLP
alone are in [`otlp.md`](otlp.md).

## Deploy and change events

Your CI pipeline sends deploys, config changes and feature-flag flips to `POST /api/events` (the
**Send deploy events** tile on the Integrations page has a ready-made `curl` step). Alerts and
findings then name the change that came just before a problem. How events are joined to metrics
(service, environment, time) is in
[`finding-drilldown.md`](finding-drilldown.md#how-are-deploy-events-joined-to-metrics-and-findings).

Before CI is set up, Ops Signals finds deploys in Prometheus on its own: a service reporting a new
version on its `*_build_info` metric, or a new ReplicaSet from kube-state-metrics. These show in the
same places as CI's deploys, tagged "Found automatically", and a deploy CI sends later replaces the found one. See
[`deploy-discovery.md`](deploy-discovery.md).

## Findings as Prometheus metrics

`GET /api/metrics` includes the active findings as `ops_signals_active_findings{service, metric,
cluster, evidence, severity}`. Scrape it and an ordinary alert rule can page on "strong evidence on
checkout" through your existing Alertmanager routes, and any dashboard can chart findings. See
[`finding-metrics.md`](finding-metrics.md).
