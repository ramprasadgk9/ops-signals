# Findings as metrics

Ops Signals' `GET /api/metrics` endpoint includes the active findings as Prometheus metrics. Add it
as a scrape target and your existing alert rules, Alertmanager routes and Grafana dashboards can use
findings like any other metric, with no plugin and no new tool.

## What it's for

Findings are on the Findings page, in the Grafana plugin and in Slack. People open those to look.
Many teams page someone only from Prometheus alert rules, routed by Alertmanager to the person on
call. With these metrics, a finding can go through those same routes:

- **Page only when Ops Signals has strong evidence.** An ordinary alert rule, with your usual
  routing, silences and on-call rotation.
- **Show findings on the dashboards people already use**, next to the service's latency and error
  graphs.
- **See the history.** Prometheus keeps the series, so "how often did payments have a problem this
  month" is a query.

The metrics say *that* something is wrong and where. The finding in Ops Signals still says *what*
happened, what changed, and how it was fixed last time.

### How it differs from the UI, the plugin, the REST API and MCP

They all show the same findings, to different readers:

| | Findings page, Grafana plugin, `GET /api/findings`, MCP | `GET /api/metrics` |
| --- | --- | --- |
| Read by | A person, a script or an AI client, when they ask | Prometheus, by itself, on every scrape (every 15-30 s) |
| Gives | Each finding in full: what happened, what changed, seen before | Counts per service, metric, evidence and severity |
| Then | Someone reads it | Prometheus keeps the history; alert rules check it; Alertmanager pages the person on call |

Prometheus can only read its own text format from a scrape target. It can't call the REST API or
MCP, so without this endpoint an alert rule can't see findings. Typically both are used: the alert
rule pages someone at 03:00, and they open the finding to see why.

## The metrics

```
ops_signals_active_findings{service="checkout", metric="http_request_duration_seconds", cluster="eu", evidence="strong", severity="critical"} 1
ops_signals_active_findings{service="payments", metric="error_rate", cluster="", evidence="moderate", severity="significant"} 1
ops_signals_active_findings_dropped 0
ops_signals_active_findings_up 1
```

| Metric | Meaning |
| --- | --- |
| `ops_signals_active_findings` | Active findings, counted the way the Overview page counts them: a problem that every run sees again is one finding, and it stops counting when a case on it is closed or when it is older than the window (24 hours). |
| `ops_signals_active_findings_dropped` | Findings left out because of the series cap (see below). Normally 0. |
| `ops_signals_active_findings_up` | 1 when the findings could be counted, 0 when the database couldn't be read. The other metrics on the endpoint are still served. |

Labels:

| Label | Values |
| --- | --- |
| `service` | The finding's service; `unknown` when the metric has no service label |
| `metric` | The metric the finding is about |
| `cluster` | The cluster, or empty |
| `evidence` | The finding's badge ([finding-trust.md](finding-trust.md)): `strong`, `moderate`, `data_problem` or `team_confirmed` for findings in **Needs attention**, `context` for the rest |
| `severity` | `critical`, `significant` or `normal` |

There is no finding id or pod label, on purpose: those would make a new series for every finding.
To keep the number of series small, at most 500 are emitted, the ones most worth alerting on first
(strong evidence, then critical). Findings beyond that are counted in
`ops_signals_active_findings_dropped`.

## Reading it in Prometheus

In Prometheus's **Graph** page, run `ops_signals_active_findings`. The **Table** tab has one row per
combination of labels. A row such as

```
ops_signals_active_findings{service="checkout", metric="cpu_usage", evidence="data_problem", severity="significant", job="ops-signals", instance="..."}  3
```

reads: "checkout's `cpu_usage` has 3 open problems where the metric stopped reporting or froze, and
they matter (significant)". `job` and `instance` are added by Prometheus and say where it read the
line. A service and metric can have several rows, one per evidence and severity. Labels with an
empty value (such as `cluster` when findings have none) aren't shown.

Queries that are easier to read than the full table:

| Question | Query |
| --- | --- |
| How many active findings in all (the Overview page's number) | `sum(ops_signals_active_findings)` |
| How many per service, most first | `sort_desc(sum by (service) (ops_signals_active_findings))` |
| How many of each evidence | `sum by (evidence) (ops_signals_active_findings)` |
| Only the ones that need attention | `sum by (service) (ops_signals_active_findings{evidence!="context"})` |
| What the example alert below pages on | `sum by (service) (ops_signals_active_findings{evidence="strong"}) > 0` |

The **Graph** tab of `sum by (service) (ops_signals_active_findings)` shows the count per service over
time: it goes up as problems are found and down as cases are closed.

## Set it up

1. Add Ops Signals to your Prometheus scrape config. Scrape **one** backend. If the web UI backend
   and the Grafana plugin backend share a database, both report the same findings, and scraping
   both counts every finding twice.

   ```yaml
   scrape_configs:
     - job_name: ops-signals
       metrics_path: /api/metrics
       static_configs:
         - targets: ["ops-signals:8000"]
       # Only when OPS_SIGNALS_API_TOKEN is set:
       authorization:
         credentials: <your API token>
   ```

   The endpoint needs the API token whenever `OPS_SIGNALS_API_TOKEN` is set, because the labels
   name your services and metrics ([security-model.md](security-model.md)).

2. Add an alert rule. For example, page when a service has a finding with strong evidence for 5
   minutes:

   ```yaml
   groups:
     - name: ops-signals
       rules:
         - alert: OpsSignalsStrongEvidence
           expr: sum by (service) (ops_signals_active_findings{evidence="strong"}) > 0
           for: 5m
           labels:
             severity: page
           annotations:
             summary: "Ops Signals found a problem with strong evidence on {{ $labels.service }}"
         - alert: OpsSignalsFindingsUnavailable
           expr: ops_signals_active_findings_up == 0
           for: 15m
   ```

   If Alertmanager also sends alerts to Ops Signals ([alert-enrichment.md](alert-enrichment.md)),
   route `OpsSignalsStrongEvidence` past that receiver: it is already a finding.

3. On a dashboard, `sum by (service, evidence) (ops_signals_active_findings)` charts active findings
   per service.

### On the local stack

The Prometheus that `./scripts/run_all.sh` starts (http://localhost:9090) doesn't scrape Ops Signals
by default. To try it, add this job under `scrape_configs:` in
`grafana/prometheus/prometheus.alerting.yml` (the file `run_all.sh` uses; `prometheus.yml` when you run
`docker-compose.yml` alone):

```yaml
  - job_name: ops-signals
    metrics_path: /api/metrics
    static_configs:
      - targets:
          - host.docker.internal:8001
```

Then reload Prometheus with `curl -X POST http://localhost:9090/-/reload`. If the change isn't picked
up (some editors replace the file, and the container keeps the old one), restart the container. The
**ops-signals** target on http://localhost:9090/targets should be **UP**.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `OPS_SIGNALS_FINDING_METRICS_ENABLED` | `true` | Include findings on `/api/metrics` |
| `OPS_SIGNALS_FINDING_METRICS_WINDOW_HOURS` | `24` | Findings created this recently count, like the Overview page's default |
| `OPS_SIGNALS_FINDING_METRICS_MAX_SERIES` | `500` | Most series emitted |
| `OPS_SIGNALS_FINDING_METRICS_CACHE_SECONDS` | `30` | Scrapes this close together reuse the last count instead of reading the database again |

## Limits

- A finding counts until its case is closed or it ages out of the window. A problem that went away
  without a case keeps counting until then, as on the Overview page.
- The value is a count of findings, not how bad the change is. For the size of the change, open the
  finding.
- Behavior findings (patterns across several metrics) are not included yet.
