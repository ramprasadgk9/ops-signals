# Metric Usage

With thousands of metrics, most are on no dashboard and in no alert. Metric Usage (the **Metric
Usage** page, `/metric-usage`) shows which ones are, and which ones had problems that nobody would
have seen. Every 6 hours it reads Grafana dashboards and alert rules plus Prometheus alerting and
recording rules, takes the metric names from their queries, compares them with every metric in each
Prometheus connection and with recent findings, and sorts each metric into one group:

- **Blind spot**: on no dashboard or alert, and had significant or critical findings recently. Each
  one links to its finding and can become a case.
- **Missing**: a dashboard or alert reads a metric that no longer exists, so it shows nothing.
- **Not watched**: everything else, biggest first.
- **Watched**: on a dashboard or in an alert, directly or through recording rules. Last on the page
  and closed: there's nothing to do there, but it shows which dashboards and alerts read each
  metric, so you can check your dashboards were found before you drop anything.

The page opens with the unused share of stored series, the problems nobody would have seen, and how
coverage has moved since the oldest kept check. The **Findings** cards say which dashboard or alert
shows each metric, and the **Overview** names the blind spots when there are any.

## Set it up

It needs read-only Grafana access: in Grafana, **Administration -> Service accounts**, add one with
the **Viewer** role and create a token. Then set the URL and token in `.env`; the folder, metric and
interval settings are optional:

```bash
OPS_SIGNALS_GRAFANA_URL=https://grafana.example.com
OPS_SIGNALS_GRAFANA_TOKEN=glsa_...
OPS_SIGNALS_METRIC_USAGE_EXCLUDE_FOLDERS=Scratch,Test*
OPS_SIGNALS_METRIC_USAGE_IGNORE_METRICS=go_*
OPS_SIGNALS_METRIC_USAGE_INTERVAL_HOURS=6
```

With `docker-compose.packaged.yml`, put the same lines in the `.env` next to it and run `up -d`
again. The URL is as the backend container sees it, so a Grafana on the same machine is
`http://host.docker.internal:3000`, not `localhost`. With Helm, set them under `backend.env`, and
put the token in the Secret named by `prometheusConnections.secretName`, whose keys all become
backend environment variables.

You don't list dashboards or alert rules one by one: with the URL and token it reads every
dashboard and Grafana alert rule the token can see, and Prometheus alerting and recording rules come
from your Prometheus connections without extra settings.

The page counts unused storage in series. To also see an estimated monthly cost under that count,
set what 1,000 active series cost you per month, `OPS_SIGNALS_METRIC_USAGE_COST_PER_1K_SERIES` (and
`OPS_SIGNALS_METRIC_USAGE_CURRENCY`, default `USD`). There is no built-in price, and the estimate is
only as good as the rate: real bills also depend on samples, retention and queries.

With several Prometheus connections, a panel counts only on the connections its Grafana datasource
reads: those with the same URL, or those naming it under `grafana_datasources` in the connections
file. Name it there when tenants share one URL, or when Grafana reaches Prometheus by another host
name; panels on a datasource that matches no connection are left out, with a warning.

**Run now** on the page starts a check without waiting for the schedule. All settings are listed in
[`.env.example`](../.env.example).

## Acting on unused metrics

Each **Not watched** metric has two buttons, because an unused metric means one of two things:

- **Add to Grafana**: it matters and nobody watches it. The dialog gives a query that fits the
  metric's type (a rate for counters, the 95th percentile for histogram buckets, the value for
  gauges) and the steps to put it on a dashboard or an alert rule. Nothing is created in Grafana.
- **Drop**: nobody needs it. The dialog gives Prometheus scrape config that stops storing it, one
  `metric_relabel_configs` rule with `action: drop` under each scrape job that collects it. Tick
  several metrics to get one config for all of them. You copy it into `prometheus.yml` and reload;
  Ops Signals changes nothing itself.

Only whole metrics are dropped, never single labels: dropping a label merges series and corrupts what
is left. Drop isn't offered for metrics with recent problems, metrics a recording rule makes (remove
the rule instead), `up` and `scrape_*` (Prometheus makes them), metrics whose scrape job isn't
known, and metrics first seen less than 7 days ago, so a new metric's team has time to build its
dashboard. Metrics Ops Signals analyzes, or that a query reads by a name pattern, can be dropped with
a warning.

"Not used" means not used by what the check reads. Queries people run by hand, scripts and
autoscalers that call the Prometheus API, and other Grafana instances aren't seen, so the dialog
lists what was and wasn't checked next to the Copy button. The config works for metrics Prometheus
scrapes; metrics sent by remote write or OTLP have to be dropped where they're sent from. Series
with no `job` label are called out and not counted in what the rule drops.

Jobs are named by the series' `job` label, which is usually the scrape config's `job_name`. With
relabeling or prometheus-operator they differ: put the rule in the job that sets that label (or the
ServiceMonitor's `metricRelabelings`). Metrics from several Prometheus connections get one config
block each, since each goes into its own server's config.

The scrape jobs come from `count by (__name__, job)` and the types from Prometheus
`/api/v1/metadata`; where a backend doesn't serve metadata, types are guessed from names.

## Recording rules nobody reads

**Recording rules nobody reads** lists rules whose output no dashboard, alert or other rule reads,
following chains: a rule that only feeds another unread rule is unread too. A rule whose output had
recent problems is a blind spot instead, not listed here. **How to remove** says which group to
delete it from, with a warning when a query reads metrics by a name pattern that matches it.
