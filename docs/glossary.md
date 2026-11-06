# Glossary

What the words in Ops Signals mean, in plain language. Part 1 covers Ops Signals' own words
(finding, case, analyzer, ...); part 2 covers the tech around it (Prometheus, Mimir, tenant, OTLP,
...). Each term links to the doc that explains it in full.

In the app, **What's what?** in the subtitle of Findings, Cases, Behavior Intelligence and Recurring
problems (and of the Grafana plugin's Overview) shows the same chain and the words that page uses.

## How the pieces fit

Ops Signals goes from signal to finding to case to memory. An analyzer checks one metric and
produces a **signal**. Signals become a **finding**: a symptom ("latency on checkout went up after
deploy 1.4.2"), not a diagnosis. When you decide a finding is a real problem worth working on, you
open a **case** and record the root cause and the fix. A fixed case goes into **operational
memory**, so the next time something looks like it, Ops Signals shows what fixed it.

| Step | What it is | Who makes it |
| --- | --- | --- |
| Signal | One analyzer's raw output on one metric | Ops Signals (you rarely see these) |
| Finding | A symptom: this metric changed, with the evidence | Ops Signals |
| Case | A problem: a finding you decided is real and are working on | You |
| Memory | What a fixed case taught you, saved to be found again | Ops Signals, from your case |

# Part 1: Ops Signals words

## Getting data in

### Metric

A metric is a number your system reports over time, such as CPU use, request rate or latency.

### Series

A series is one metric for one set of labels, for example latency on one pod. A metric reported by
6 pods has 6 series. See [Labels](#labels).

### Source

A source is where metrics come from: Prometheus (Ops Signals reads from it), OTLP (an OpenTelemetry
Collector sends to it) or a CSV upload. See [`data-sources.md`](data-sources.md).

### Service

A service is the app a metric belongs to, read from a label: `job` or `service` in Prometheus,
`service.name` in OpenTelemetry. A metric with no such label shows as `unknown`.

### Deploy

A deploy is a new version of a service going out, as Ops Signals knows it: sent by CI or found in
the metrics. See [`deploy-discovery.md`](deploy-discovery.md).

## Analysis

### Analyzer

An analyzer is a check that asks one question about one metric, such as "did the normal level
change?" or "did the data stop?". There are 9. An analyzer detects a behavior; it doesn't explain
it or name a cause. See [`analyzers-explained.md`](analyzers-explained.md).

### Router

The router picks which analyzers suit each metric, using rules, not AI. You don't choose analyzers
yourself. See [`analyzer-recommendation.md`](analyzer-recommendation.md).

### Series profile

A series profile is a summary of a metric's shape (trend, repeating pattern, spikiness, data
quality) that the router reads to pick analyzers.

### Signal

A signal is one analyzer's raw output on one metric. Ops Signals groups signals into findings, so
you rarely see a signal on its own.

### Analysis run

An analysis run is one pass of the analyzers over a set of metrics, started by hand on **New
Analysis** or by a schedule.

### Autonomous Analysis

Autonomous Analysis is the schedule: which services and metrics to watch and how often to check
them. See [`autonomous-analysis-preview.md`](autonomous-analysis-preview.md).

## Results

### Finding

A finding is a symptom on one metric: what changed, when, and the evidence. It is not a diagnosis.
"Latency on checkout went up" is a finding; "the cache was misconfigured" is a root cause, and that
goes on a case. See [`finding-anatomy.md`](finding-anatomy.md).

### Finding vs alert

A finding is something unusual Ops Signals noticed, which may have no alert rule. An alert is
something your own alerting rule decided to page someone for. See [Alert](#alert).

### Evidence badge

The evidence badge says how much to trust a finding. **Strong evidence**: two checks agree.
**Moderate evidence**: one check saw the level move and stay there. **Data problem**: the metric
stopped reporting or froze. **Context only**: a single unusual value, a pattern or a forecast.
**Over**: it needed attention and ended more than an hour ago. See
[`finding-trust.md`](finding-trust.md).

### Needs attention and Context only

Needs attention and Context only are the two lists on the Findings page. Needs attention is worth a
look now; Context only is background for when you're already investigating something. A problem
that ended moves from Needs attention to Context only an hour later.

### Finding states

A finding's state says whether its problem is still going on, which list it's in, and what your
team did about it. Each run that sees the problem again adds a finding to the same problem; nothing
is overwritten.

| State | Where you see it | Means |
| --- | --- | --- |
| **Still happening** | Timing chip, "Started 09:40 · still happening" | Still going at the latest analyzed data, from the last 2 hours |
| **Still going when the data ended** | Timing chip | Still going at the end of older data, such as an uploaded file |
| **Over** (timing) | Timing chip, "09:40–09:45 · over" | The data went on after the last bad reading; a spike's card adds "Normal again since 09:45" |
| **Over** (badge) | Evidence badge, in Context only | It needed attention and ended more than an hour ago |
| **Seen in N runs** | Chip on the card | N runs saw the same problem; it's counted once |
| **Needs attention** / **Context only** | The two lists | Worth a look now / background |
| **Real problem**, **Not a problem**, **Expected change** | "Was this real?" | Your team's answer |
| **Case open** / **Case closed** | Cases | A closed case takes the problem out of the Overview counts |

Only data problems and spikes move to Over; level changes and trends don't yet. See
[finding states](operational-findings.md#finding-states-from-found-to-over).

### Was this real?

"Was this real?" is your team's answer on a finding: **Real problem**, **Not a problem**, or
**Expected change** (real but planned, like a deploy). The answers build your team's own trust rate
per service.

### Combined pattern

A combined pattern (behavior finding) is a problem that only shows when several metrics are looked
at together. It is listed on **Behavior Intelligence** and on Findings. See
[`behavior-intelligence.md`](behavior-intelligence.md).

### Behavior pattern

A behavior pattern is the rule a combined pattern matched. Patterns are built in, mined from your
data, or written by an admin in the pattern builder.

### Blind spot

A blind spot is a metric that had real problems recently but is on no dashboard and in no alert, so
nobody would have seen them. See [`metric-usage.md`](metric-usage.md).

## Investigating

### Alert

An alert is something your alerting (Alertmanager or Grafana alerting) decided to page someone for.
Your rule raised it, not Ops Signals; Ops Signals adds what happened, what changed just before and
past cases to it. See [`alert-enrichment.md`](alert-enrichment.md).

### Case

A case is a problem you're working on, opened from a finding or a combined pattern. It tracks the
investigation, the root cause and the fix. The Cases page splits them into Open, In progress, On
hold and Resolved. See [`operational-cases.md`](operational-cases.md).

### Finding vs case

A finding is a symptom Ops Signals noticed; a case is a problem you decided to work on. Many
findings never become cases.

### Root cause

A root cause is why the problem happened, recorded on the case.

### Resolution

A resolution is what fixed the problem, recorded on the case. It is what **Seen before** shows the
next time something similar happens.

## Learning from the past

### Operational memory

Operational memory is past cases saved so they can be searched by similarity. A match means "looks
alike", not "same cause". See [`operational-memory.md`](operational-memory.md).

### Seen before

Seen before means past cases look like this finding or case, and shows the closest one and what
fixed it.

### Recurring problem

A recurring problem is a group of past cases that keep coming back, with the causes found and what
to do next. They are listed on **Recurring problems**.

### Fix didn't hold

Fix didn't hold means the same problem came back on the same service within 30 days of a fix, and
names the old fix. See [When a fix didn't stick](operational-memory.md#when-a-fix-didnt-stick).

### Imported incident

An imported incident is a past incident or postmortem you loaded in, so memory can match against it
from day one. See [`importing-incident-history.md`](importing-incident-history.md).

# Part 2: The tech around it

## Prometheus and metrics

### Prometheus

Prometheus is an open-source tool that collects metrics and stores them over time. It is Ops
Signals' main source: Ops Signals reads metrics from it and analyses them. See
[`standalone-prometheus-analysis.md`](standalone-prometheus-analysis.md).

### Scrape

A scrape is Prometheus visiting each app every few seconds to read its current numbers (pull).
Prometheus does the scraping, not Ops Signals.

### Exporter

An exporter is a small program that turns a system's stats into Prometheus metrics, for example for
a database or a machine. Its metrics are analysed like any other.

### Labels

Labels are name tags on a metric, such as `service="checkout"` or `pod="checkout-7f9"`. One set of
labels makes one series. Ops Signals reads them to know a metric's service, pod, tenant and cluster.

### PromQL

PromQL is Prometheus's query language, for example `rate(http_requests_total[5m])`. Metric Usage
reads the PromQL in your dashboards and alerts, and **Add to Grafana** gives you a query to paste.

### Recording rule

A recording rule is a query Prometheus runs on a schedule and saves as a new metric. Metric Usage
flags recording rules no dashboard or alert reads.

### Alerting rule

An alerting rule is a query plus a condition ("error rate above 5% for 10 minutes") that fires an
alert. A metric used in one counts as watched on Metric Usage.

### build_info metric

A `build_info` metric reports an app's version, for example `checkout_build_info{version="1.4.2"} 1`.
When a new version shows up, Ops Signals records a deploy.

### Cardinality

Cardinality is how many series a metric has. Many pods or many label values mean high cardinality,
which means more storage and more work for analysis.

## Scaling Prometheus: Mimir, tenants and clusters

### Prometheus-compatible backend

A Prometheus-compatible backend answers the same queries as Prometheus but stores more, or for
longer: Grafana Mimir, Thanos and VictoriaMetrics are examples. Ops Signals connects to one the same
way it connects to Prometheus. See [`data-sources.md`](data-sources.md).

### Mimir

Grafana Mimir is an open-source, scalable Prometheus-compatible store that holds many teams'
metrics. Ops Signals works with it, including several tenants and several clusters. See
[Mimir, Thanos and other backends](standalone-prometheus-analysis.md#mimir-thanos-and-other-multi-source-backends).

### Tenant

A tenant is one team's or customer's separate space inside a shared backend such as Mimir; each
tenant sees only its own metrics. Ops Signals picks a tenant with the `X-Scope-OrgID` header, and
reads several tenants when each is listed as a named connection. See
[Several tenants](standalone-prometheus-analysis.md#several-tenants-named-connections).

### Cluster

A cluster is one Kubernetes cluster or group of servers; one backend can hold metrics from many.
Ops Signals analyses each cluster on its own, so problems from two clusters don't get mixed. See
[Several clusters](standalone-prometheus-analysis.md#several-clusters-behind-one-endpoint).

### HA replicas

HA replicas are two identical Prometheus servers running side by side, so one can fail; both send
the same data. Ops Signals counts the copies once (`OPS_SIGNALS_PROMETHEUS_REPLICA_LABELS`). See
[HA replica pairs](standalone-prometheus-analysis.md#ha-replica-pairs).

### Connection

A connection is one place Ops Signals reads metrics from: a URL, plus a tenant if there is one.
Several can be listed in a connections file.

## OpenTelemetry

### OpenTelemetry

OpenTelemetry (OTel) is an open standard for collecting metrics, traces and logs from apps,
whatever tool stores them. Ops Signals takes in its metrics. See [`otlp.md`](otlp.md).

### OTLP

OTLP (OpenTelemetry Protocol) is how OpenTelemetry data is sent: apps push it, where Prometheus
pulls. Ops Signals accepts OTLP metrics over HTTP (not gRPC) and analyses them as they arrive. It is
not OLTP, a database term.

### Collector

The OpenTelemetry Collector is a program that receives telemetry from apps and forwards it to
where it is stored or analysed. See [`otlp.md`](otlp.md).

### service.name

`service.name` is the OpenTelemetry attribute that names the app. It becomes the finding's service.

## Grafana and alerting

### Grafana

Grafana is an open-source tool for dashboards and charts of your metrics. Metric Usage reads its
dashboards and alerts, and Ops Signals also runs inside it as a plugin.

### Data source

A data source is a connection inside Grafana to where metrics live, such as a Prometheus. The
Grafana plugin analyses through Grafana's data sources.

### Dashboard

A dashboard is a Grafana page of charts. A metric on a dashboard counts as watched on Metric Usage.

### Grafana app plugin

A Grafana app plugin puts a whole app inside Grafana. Ops Signals ships one with the web UI's
features, using Grafana's sign-in and roles. See
[`grafana-plugin-local-setup.md`](grafana-plugin-local-setup.md).

### Alertmanager

Alertmanager is Prometheus's tool that receives fired alerts and decides who gets paged and how. It
can send alerts to Ops Signals by webhook, so they get what changed and past cases added.

### Webhook

A webhook is a URL one system calls to tell another that something happened. Alertmanager, CI
deploys and Slack connect to Ops Signals this way.

## Kubernetes

### Kubernetes

Kubernetes (K8s) is a system that runs apps in containers across many machines.

### Pod

A pod is one running copy of an app; a service often has several. Findings can say which pods a
change came from, such as "1 of 6 pods".

### Namespace

A namespace is a folder-like group of apps inside a Kubernetes cluster. Autonomous Analysis can use
it to choose what to watch.

### ReplicaSet

A ReplicaSet is the set of pods for one version of an app. A new ReplicaSet (from kube-state-metrics)
usually means a deploy, and Ops Signals records it as one.

### Helm chart

A Helm chart is a packaged way to install an app on Kubernetes. See [`deploy.md`](deploy.md).

## Inside Ops Signals

### PostgreSQL

PostgreSQL is the database that holds findings, cases and your answers. See
[`architecture.md`](architecture.md).

### Qdrant

Qdrant is a vector database: it finds things similar in meaning rather than exact matches. Ops
Signals uses it only as a search index for Seen before and Ask Ops Signals; it can be rebuilt from
PostgreSQL.

### Embedding

An embedding is text turned into a list of numbers so that similar meanings land close together. It
lets past cases and docs be found by meaning.

### AI provider

An AI provider is a language model (LLM), run locally or through an API. It is optional: everything
core works without one. See [`ai-features.md`](ai-features.md).

### MCP

MCP (Model Context Protocol) is a standard way for AI assistants and IDEs to use a tool's data. Ops
Signals' MCP server lets one read findings, cases and runs, and update cases in write mode. See
[`mcp-server.md`](mcp-server.md).

### OIDC

OIDC (single sign-on) lets people sign in with their company login, for example Keycloak. See
[`web-ui-sign-in.md`](web-ui-sign-in.md).

### API token

An API token is a secret key a script or system shows to prove it may call the API. See
[`security-model.md`](security-model.md).

### Roles

There are three roles: a **Viewer** looks and asks, an **Editor** also runs analyses and works
cases, an **Admin** also changes settings. See [`access.md`](access.md).

### CI

CI (continuous integration) is the system that builds and ships your code. It can send deploys to
`POST /api/events`.
