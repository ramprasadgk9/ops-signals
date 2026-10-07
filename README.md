# Ops Signals

[![CI](https://github.com/ramprasadgk9/ops-signals/actions/workflows/ci.yml/badge.svg)](https://github.com/ramprasadgk9/ops-signals/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/ramprasadgk9/ops-signals)](https://github.com/ramprasadgk9/ops-signals/releases)

Ops Signals is a vendor-neutral Operational Intelligence framework that transforms time-series data into explainable findings, investigation cases, and searchable operational memory.

It is designed to help teams move from raw metrics to actionable operational context without replacing existing observability or incident platforms.

![Ops Signals demo: a deploy causes a latency shift, the alert is enriched with what happened, what changed, and a matching past incident](docs/screenshots/images/demo/ops-signals-demo.gif)

### Try it in one command

```bash
git clone https://github.com/ramprasadgk9/ops-signals.git
cd ops-signals
docker compose -f docker-compose.demo.yml up
```

This starts Ops Signals with an incident already in progress: a deploy, then a latency shift, then
a Prometheus alert. About a minute later, open **http://localhost:8090** to see the enriched alert
as it would appear in Slack, and **http://localhost:8080** for the full UI. You only need Docker:
no Python, Node, Slack workspace or data of your own. See [`docs/demo.md`](docs/demo.md) for what's
running and how it works.

> **Run it on a trusted network.** The API has no authentication unless you set
> `OPS_SIGNALS_API_TOKEN`. Don't expose it to the internet. See [Security model](#security-model).

Designed and implemented by Ramprasad Goturkarnam ([@ramprasadgk9](https://github.com/ramprasadgk9)), who is also the project's primary contributor and maintainer.

New here? [`docs/README.md`](docs/README.md) is a guided path through every doc referenced below.

## In One Sentence

Upload a metric time series, let the analyzers explain what changed, promote important findings into cases, and reuse prior cases as searchable operational memory.

## The Problem

Raw time-series points are noisy, high-volume, and hard to reason about directly. A dashboard can
plot them, but plotting them isn't the same as explaining them - and today those two get treated as
if they were the same thing.

Take a concrete example: `payments-api` `cpu_usage` climbs from ~78% to ~95% over an hour.

- **A dashboard shows the line moved, not why that matters.** Grafana renders the series and, at
  best, flags a threshold breach - it doesn't expose what detection logic decided this mattered,
  and there's no way to change that logic without hand-editing dashboard JSON or alert rules.
- **A number isn't an explanation.** "95%" doesn't say whether this is a new baseline, a one-off
  spike, or a slow trend - someone still has to eyeball the graph and decide.
- **Once you know something's wrong, dashboards stop there.** There's no next step - no
  investigation trail, no prompt for what to check first.
- **If you do investigate and file a Jira ticket, the work mostly dies in that ticket.** The root
  cause and the fix that worked sit in a ticket nobody queries again until the same pattern shows
  up on a different service months later, and someone reinvestigates from zero.
- **None of that accumulated experience feeds back into anything.** It doesn't inform the next
  alert, the next dashboard, or the next engineer's triage - it isn't stored anywhere a system (or
  a person) can ask "have we seen this before, and what fixed it?"

Ops Signals is built to close each of those gaps, one to one:

1. **Explainable findings, not just a plotted line.** Analyzers run against the metric and produce
   a stated conclusion ("sustained baseline shift," "anomalous window") - the logic is visible and
   swappable, not a fixed threshold buried in dashboard JSON.
2. **A written explanation, not just a number.** Every finding carries a plain-language summary
   ("CPU spike on payments-api ... sustained elevated utilization") alongside the raw score - see
   [Example Operational Finding](#example-operational-finding).
3. **A case gives you the next step.** A finding can be promoted into a case with investigation,
   RCA, and resolution fields - so "something's wrong" turns into "here's what to check and track."
4. **A resolved case becomes golden data, not a dead ticket.** Once a case is resolved, it's
   automatically indexed into Qdrant - the root cause and fix stay retrievable instead of sitting
   in a ticket nobody reopens.
5. **That golden data feeds back into the loop.** `GET /api/alert-context` lets an external
   system such as an alert manager ask "has this happened before, was it real, how was it resolved"
   *before* it pages anyone, instead of starting from zero every time - see
   [`docs/architecture.md`](docs/architecture.md).

See [`docs/vision.md`](docs/vision.md) for the fuller five-layer narrative behind this.

## What Ops Signals Does

- **Takes data in from where it already is**: Prometheus (on a schedule or on demand), OTLP pushed
  from an OTel SDK or Collector, CSV upload, and Alertmanager alerts. Deploy and config events come
  from your CI through `POST /api/events`.
- **Runs analyzers picked for each metric**: baseline shift, change point, anomaly and outlier
  detection, trend, pattern discovery, forecasting and data health. A config-driven router picks
  them, and new analyzers are added through config without touching core code (see
  [Analyzers](#where-to-find-each-feature)). An optional AI second opinion can flag disagreement
  with the router but never overrides its pick.
- **Turns analyzer signals into findings**: a title, a plain-language summary, a category, a health
  status and an importance score. Declarative rules across several metrics produce behavior findings.
- **Says where a change came from and what came before it**: drill-down (opt-in) shows which pods
  a change came from, and findings and alerts name the deploy or config change just before it,
  including which new pods that deploy started - see
  [`docs/finding-drilldown.md`](docs/finding-drilldown.md).
- **Watches Prometheus on its own**: configure scope and policy, run once or on a schedule, see
  results inline.
- **Enriches alerts**: when a Prometheus alert fires, Ops Signals analyzes the alerting series,
  matches recent deploys, looks up past cases, and posts one Slack message answering "what happened,
  what changed, have we seen it before" - see [Alert Enrichment](#alert-enrichment-alertmanager-to-slack).
  High-importance findings can go to Slack too - see [Slack Notifications](#slack-notifications).
- **Tracks investigations as cases**: a finding or behavior finding becomes a case with
  investigation, RCA, corrective action and outcome. Resolved cases are indexed into Qdrant.
- **Remembers**: similar-case search over past cases, and `GET /api/alert-context`, which lets an
  external system ask for prior outcomes, similar resolved cases and recurrence before it acts.
- **Answers questions**: Ask Ops Signals, a chat over cases, findings, behaviors, analyzers and
  these docs.
- **Works where you work**: a React web UI, a Grafana plugin and an MCP server.
- **Is measured**: a benchmark suite checks router accuracy, detection accuracy, false alarms and
  behavior intelligence against known-answer datasets - see [`benchmark/README.md`](benchmark/README.md).

Every detection analyzer is a published, peer-reviewed method, not invented here - see
[`docs/analyzer-methodology.md`](docs/analyzer-methodology.md) for citations. The router's
suitability *scores* are heuristic and not yet validated against outcomes; that same document says
so plainly and links to the tracking infrastructure built to close that gap.

### What Makes It Different

- It's open and self-hostable, not a closed black box
- It treats detector output as input to higher-level operational interpretation, not the end product
- It adds a separate behavior reasoning layer for cross-metric patterns, instead of bolting rules onto individual metrics
- It emphasizes deterministic, explainable answers over free-form generation
- It keeps PostgreSQL as the system of record and Qdrant as a semantic retrieval index - never the other way around
- It shows which analyzers and signals contributed to each result, not just a final score

**How it compares.** Robusta/HolmesGPT add Kubernetes context and LLM investigation to alerts,
Keep deduplicates and routes alerts across tools, and Grafana Sift runs ML checks in Grafana Cloud.
Ops Signals needs no Kubernetes and no LLM: it explains the alerting metric itself and links it to
past resolved cases. It can run alongside any of them. See [`docs/comparison.md`](docs/comparison.md),
including where those tools are ahead.

### How It Works

```mermaid
flowchart LR
  A[Upload CSV or metric sample] --> B[Normalize and store]
  B --> C[Run analyzers]
  C --> D[Generate signals]
  D --> E[Aggregate findings]
  D --> E2[Cross-metric behavior findings]
  E --> F[Open or create a case]
  E2 --> F
  F --> G[Ask questions and reuse memory]
  F --> H[External alert manager checks prior outcomes]
  I[Alertmanager alert] --> C
  F --> J[Enriched alert in Slack]
  I --> J
```

This is not a replacement for Prometheus, Datadog, Grafana, or incident-management platforms.
It does not currently perform autonomous remediation.
Historical similarity does not prove two cases share the same root cause.

## Quick Start

### Choose How to Run It

| You want to | Use | Needs |
| --- | --- | --- |
| See it working in a minute, with a scripted incident | `docker compose -f docker-compose.demo.yml up` ([demo](docs/demo.md)) | Docker |
| Try it on your laptop, with sample metrics or your own Prometheus | `./scripts/setup.sh`, then `./scripts/run_all.sh` (the steps below) | Docker, Python, Node |
| Run it for your team on one server | `docker compose -f docker-compose.packaged.yml up -d` ([Deploy for Your Team](#deploy-for-your-team)) | Docker |
| Run it in Kubernetes | `helm upgrade --install ops-signals ./helm/ops-signals` ([Deploy for Your Team](#deploy-for-your-team)) | Kubernetes, Helm |
| Use it inside Grafana | the Grafana plugin ([Grafana Plugin](#grafana-plugin)) | Grafana, plus one of the two above |

The demo doesn't read your data. The laptop install starts its own Prometheus with mock metrics, so
it works before you connect anything. The team installs read only from the Prometheus you point
them at.

### Try It on Your Laptop

The steps below set up a development install that you can point at your own data.

### Prerequisites

- **Git**
- **Docker**, with Compose v2 (the `docker compose` command, not the older standalone `docker-compose`) - runs PostgreSQL/TimescaleDB and Qdrant for you
- **Python 3.11, 3.12, or 3.14** - 3.13 is explicitly not supported by `scripts/setup.sh`
- **Node.js 20+** and npm - for the React frontend
- *(Optional)* **Ollama** - only needed for local AI-assisted answers (see [Enable Local AI](#optional-enable-local-ai)); everything works without it
- macOS or Linux (the scripts are bash-based; on Windows, use WSL)

Check what you already have installed:

```bash
docker compose version
python3 --version
node --version
```

### Clone the Repository

```bash
git clone https://github.com/ramprasadgk9/ops-signals.git
cd ops-signals
```

### Run Setup

```bash
./scripts/setup.sh
```

This creates a Python virtualenv and installs dependencies, runs `npm install` for the frontend, starts PostgreSQL and Qdrant in Docker, waits for both to report healthy, and initializes the database schema. First run pulls Docker images and packages, so expect it to take a few minutes. You'll see `Setup complete.` printed at the end.

### Start Ops Signals

```bash
./scripts/run_all.sh
```

This starts the backend (`:8001`), frontend (`:5174`), Postgres, Qdrant, Prometheus, and mock metrics together, all from one command.

### Open the Application

Go to **http://localhost:5174** in your browser. You should see the Overview dashboard:

![Ops Signals Overview](docs/screenshots/images/web/01-overview.png)

### Connect a Data Source

Findings will be empty on a fresh install - that's expected, nothing has been analyzed yet. Until
the first data arrives, the Overview shows a **Get data in** panel with every way in:

- **OTLP** - the endpoint to point an OTel Collector or SDK at, with a config snippet (see [OTLP](#otlp)).
- **Alertmanager** - the webhook URL and a `receivers:` snippet; **Send test alert** proves the
  whole path once alert enrichment is on (see [Alert Enrichment](#alert-enrichment-alertmanager-to-slack)).
- **Prometheus** - pulled on a schedule once `OPS_SIGNALS_PROMETHEUS_URL` is set in `.env`, or
  `OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE` for several Mimir tenants (see [Prometheus](#prometheus)).
- **Deploy events** - the URL and a `curl` step for your CI pipeline, so alerts and findings can say
  which deploy came just before a change (see [Deploy and change events](#deploy-and-change-events)).
- **Load demo data** - analyzes a bundled checkout series in seconds, or upload your own CSV from
  **New Analysis** (see [CSV Input](#csv-input)).

The same sources, with whether each is receiving, live on the **Integrations** page
(`/integrations`) afterwards; received alerts are on the **Alerts** page (`/alerts`). The APIs behind
them are `GET /api/ingestion/status` and `GET /api/alerts`.

### Optional: Enable Local AI

By default, Ask Ops Signals and the analyzer recommendation advisor run on deterministic retrieval and templates - no AI, no API key, no network calls out. To add local LLM-assisted answers on top of that (never instead of it - the deterministic behavior stays the fallback):

```bash
docker compose --profile ai up -d
```

This starts a local Ollama container and pulls a small default model (`qwen2.5:3b`, ~2GB, one-time download). Then point the backend at it:

```bash
OPS_SIGNALS_AI_ENABLED=1 OPS_SIGNALS_AI_PROVIDER=ollama ./scripts/run_all.sh
```

See [Operational Intelligence Assistant](#operational-intelligence-assistant) for exactly what changes when this is on.

Prefer a model you already run or pay for? Set `OPS_SIGNALS_AI_PROVIDER=openai_compatible` (vLLM, Azure OpenAI, Bedrock gateways, LiteLLM) or `anthropic` instead. See [Other AI Providers](docs/ask-ops-signals-assistant.md#other-ai-providers).

### Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `docker is required` | Docker isn't installed, or the daemon isn't running | Install/start Docker Desktop (or Docker Engine on Linux) |
| `Unsupported Python version selected: 3.13` | System Python is 3.13, which `setup.sh` rejects | Install 3.11, 3.12, or 3.14, then run `PYTHON_BIN=python3.12 ./scripts/setup.sh` |
| `npm is required to install frontend dependencies` | Node.js/npm isn't installed | Install Node.js 20+ |
| `postgres did not become ready in time` or `qdrant did not become ready in time` | Docker is still starting, or the port is already taken | `docker compose ps` and `docker compose logs postgres` (or `qdrant`); confirm ports `5432`/`6333` are free |
| A port (`8001`, `5174`, `9090`) is already in use | Another process is bound to it | Stop that process, or see `scripts/run_all.sh` for the ports it uses |
| `permission denied` running a script | The script isn't marked executable | `chmod +x scripts/*.sh` |

### Security model

Ops Signals is meant to run inside a trusted network, next to your Prometheus and Grafana:

- **No authentication by default.** Set `OPS_SIGNALS_API_TOKEN` and every endpoint except
  `/api/health` requires `Authorization: Bearer <token>`. The alert and event receivers accept their
  own token, or the API token if they don't have one.
- **Dangerous endpoints are off by default.** `OPS_SIGNALS_ENABLE_TESTING_API=true` turns on the
  endpoint that wipes all data. `OPS_SIGNALS_ALLOW_FILE_WRITES=true` lets the analyzer and behavior
  labs write files on the server. The dev scripts turn both on.
- **CORS** is limited to local dev origins. Add your Grafana URL with `OPS_SIGNALS_CORS_ORIGINS`.

[`docs/security-model.md`](docs/security-model.md) covers how each client (web UI, Grafana plugin,
Alertmanager) sends the token, the Helm and Compose settings, and the known limitations.

### Scripts Reference

| Script | What it does | When to use it | Ports |
| --- | --- | --- | --- |
| `./scripts/setup.sh` | Installs Python and frontend deps, starts Postgres and Qdrant, and initializes the database. | First-time setup or after a clean checkout. | Postgres `5432`, Qdrant `6333` |
| `./scripts/run_all.sh` | Starts the standalone backend, frontend, Postgres, Qdrant, Prometheus, and mock metrics for the app. | Daily local development outside Grafana. | Backend `8001`, frontend `5174`, Prometheus `9090` |
| `./scripts/multicluster.sh up`, then `app` | Starts a local Grafana Mimir with several clusters, an HA pair and two tenants, then the app with one connection per tenant. | Testing multi-cluster and multi-tenant behaviour; not for real deployments. See [`docs/testing-multicluster-locally.md`](docs/testing-multicluster-locally.md). | Mimir `9009`, plus the `run_all.sh` ports |
| `./scripts/run_grafana_stack.sh` | Builds the Grafana plugin, starts Grafana, Prometheus, mock metrics, and the plugin backend. | Testing the Grafana plugin experience. | Grafana `3000`, Prometheus `9090`, backend `8002` |
| `./scripts/test_mcp.sh` | Starts the MCP server and verifies `initialize` and `tools/list`. | Checking MCP locally without Codex. | None; stdio only |
| `MCP_MODE=mcp-write ./scripts/test_mcp.sh` | Verifies the write-enabled MCP tool list. | Confirming write-capable tools are exposed. | None; stdio only |

`3000` is reserved for Grafana, `8002` for the Grafana/plugin backend - they don't conflict with the standalone app's `8001`/`5174`.

## Deploy for Your Team

`run_all.sh` is for trying Ops Signals out: it runs from source and starts mock metrics. For a team,
run the backend, web UI and MCP server as containers, pointed at your real Prometheus. Set
`OPS_SIGNALS_API_TOKEN` for anything others can reach (see [Security model](#security-model)).

### One Server: Docker Compose

```bash
git clone https://github.com/ramprasadgk9/ops-signals.git
cd ops-signals
echo 'OPS_SIGNALS_PROMETHEUS_URL=http://host.docker.internal:9090' >> .env
docker compose -f docker-compose.packaged.yml up -d
```

The web UI is at **http://localhost:8080** and the API at `http://localhost:8000`. Set
`OPS_SIGNALS_PROMETHEUS_URL` to your Prometheus as the backend container sees it:
`host.docker.internal` is the machine Docker runs on.

**Several Mimir tenants:** list them in a connections file and add the connections overlay.
Tokens go in `prometheus-connections.env`, never in the YAML:

```bash
cp examples/prometheus-connections.yaml prometheus-connections.yaml
printf 'MIMIR_TEAM_A_TOKEN=...\nMIMIR_TEAM_B_TOKEN=...\n' > prometheus-connections.env
docker compose -f docker-compose.packaged.yml -f docker-compose.connections.yml up -d
```

### Kubernetes: Helm

```bash
kubectl create secret generic ops-signals-db \
  --from-literal=database-url='postgresql+psycopg://USER:PASSWORD@HOST:5432/ops_signals'

helm upgrade --install ops-signals ./helm/ops-signals \
  --set database.urlSecret.name=ops-signals-db \
  --set backend.env.OPS_SIGNALS_PROMETHEUS_URL=http://prometheus-server.monitoring:9090
```

**Several Mimir tenants:** put the connections file under `prometheusConnections.config` in your
values and the tokens in a Secret named by `prometheusConnections.secretName`.

Both paths, with every value to set, are in [`docs/release-packaging.md`](docs/release-packaging.md).

## Product Overview

Ops Signals ships as a standalone operational intelligence workspace and a Grafana plugin. This
section is what each surface looks like and produces; [Using Ops Signals](#using-ops-signals)
below is how to actually work with each piece.

**[View the complete screenshot gallery](docs/screenshots.md)**

### Standalone Operational Intelligence Workspace

![Ops Signals Overview](docs/screenshots/images/web/01-overview.png)

### Analyze Prometheus Data Directly

![Direct Prometheus Analysis](docs/screenshots/images/web/03-new-analysis-prometheus.png)

### See Which Pods a Change Came From

A service-level finding says *what* changed. With [drill-down](docs/finding-drilldown.md) on, it
also says *where*: one bad pod, a few, every pod, or new pods from a rollout. Each of those calls
for a different next step.

![Finding drill-down: the error increase came from two new pods, pointing to a rollout](docs/screenshots/images/web/10-finding-drilldown.png)

### Investigate and Preserve Operational Knowledge

![Case Investigation](docs/screenshots/images/web/05-case-details.png)

### Run Analysis Inside Grafana

![Grafana Analysis Results](docs/screenshots/images/grafana-plugin/02-metrics-analysis.png)

### Enriched Alerts in Slack

When a Prometheus alert fires, Ops Signals posts one message that says what happened, what changed,
and whether it has been seen before. This one is from the [demo](docs/demo.md), shown in its Slack
stand-in; see [Alert Enrichment](#alert-enrichment-alertmanager-to-slack) for real Slack.

![Enriched alert: a latency shift, the deploy before it, and a matching past incident with its fix](docs/screenshots/images/slack/enriched-alert-demo.png)

### Two ways to use Ops Signals

- **Standalone Web UI:** Supports CSV upload, direct Prometheus analysis, findings, cases, behavior intelligence, operational memory, and assistant retrieval.
- **Grafana Plugin:** Supports metric analysis within an existing Grafana and Prometheus environment using the active Grafana time range.

Alert enrichment and finding notifications have no page of their own: their output is the Slack
message.

## Architecture

Data goes through one pipeline: validation, normalization into PostgreSQL, router-selected
analyzers, signals, then findings (and, separately, cross-metric behavior findings), which can be
promoted to cases. The [diagram above](#how-it-works) shows the flow;
[`docs/architecture.md`](docs/architecture.md) has the detailed version with per-stage code
references.

Two pipelines run the same analyzers and routing: **Interactive Analysis** (`SignalPipeline`, used
by Grafana, REST, CSV and the CLI) and **Autonomous Analysis** (`MetricAnalysisExecutor`, used by
the scheduler). They share the router and analyzer implementations but not orchestration code - see
[`docs/autonomous-pipeline-architecture.md`](docs/autonomous-pipeline-architecture.md).

**Storage.** PostgreSQL is the system of record: analysis runs, normalized points, signals,
findings, cases and investigation state. Qdrant is the semantic retrieval index built from it, kept
in sync on case create and update; nothing is written to Qdrant that isn't in PostgreSQL first.

More detail:

- [`docs/architecture.md`](docs/architecture.md) - the full pipeline, a diagram, and a "Why
  This Reduces MTTR" section connecting it to operational outcomes.
- [`docs/core-domain-model.md`](docs/core-domain-model.md) - the data model: canonical
  points, signals, and the fields on each.
- [`docs/design-decisions.md`](docs/design-decisions.md) - the "why," in short ADR-style
  writeups, including why PostgreSQL and Qdrant are split this way.
- [`docs/standalone-overview-api.md`](docs/standalone-overview-api.md) - the Overview
  summary and memory statistics endpoint contracts.
- [`docs/standalone-prometheus-analysis.md`](docs/standalone-prometheus-analysis.md) - the
  direct Prometheus query flow and how it differs from Grafana datasource-based analysis.

## Using Ops Signals

Where to find each capability once the app is running.

### Where to Find Each Feature

| Feature | Where | Read more |
| --- | --- | --- |
| **UI tour**: every tab of the web UI (13) and both Grafana plugin modes, one line each | - | [`docs/ui-tour.md`](docs/ui-tour.md) |
| **Interactive analysis**: one metric at a time, from a Prometheus query or a CSV, findings right away | **New Analysis**; Grafana **Interactive Analysis** | [`docs/standalone-prometheus-analysis.md`](docs/standalone-prometheus-analysis.md) |
| **Analyzers**: 7 built in (Baseline Shift, Ruptures Change Point, Z-Score Anomaly, PyOD Outlier, Trend, STUMPY Motif, Prophet Forecast) plus Data Health, added through config; how the router picks and how far to trust it. Seasonal Anomaly is registered but the router doesn't pick it | **Analyzer Workbench** → **Recommendations** | [`docs/analyzer-plugin-framework.md`](docs/analyzer-plugin-framework.md), [`docs/analyzer-recommendation.md`](docs/analyzer-recommendation.md) |
| **Behavior intelligence**: rules across several metrics, with a worked memory-pressure example | **Behavior Intelligence**, **Behavior Lab** | [`docs/behavior-intelligence.md`](docs/behavior-intelligence.md) |
| **Analyzer workbench**: run any analyzer on sample data (**Labs**), register a new one in Python or as your own HTTP service (**Add Analyzer**), preview router scores (**Recommendations**) | **Analyzer Workbench** | [`docs/analyzer-plugin-framework.md`](docs/analyzer-plugin-framework.md#analyzer-workbench-ui), [`docs/http-analyzer-contract.md`](docs/http-analyzer-contract.md) |
| **Findings**: drill-down by pod, the deploy before a change | **Findings** | [`docs/operational-findings.md`](docs/operational-findings.md), [`docs/finding-drilldown.md`](docs/finding-drilldown.md) |
| **Investigations and cases**: ad-hoc digging into one metric or service; every case with its lifecycle (`open -> investigating -> rca_in_progress -> resolved -> closed`), RCA and outcome | **Investigations**, **Cases** | [`docs/operational-cases.md`](docs/operational-cases.md) |
| **Historical analysis**: semantic search over past cases and findings, the alert-context preview an external alert manager would see, and importing past postmortems so it works on day one | **Operational Memory** | [`docs/operational-memory.md`](docs/operational-memory.md), [`docs/importing-incident-history.md`](docs/importing-incident-history.md) |
| **Autonomous analysis**: what to watch, run once or on a schedule | **Autonomous Analysis Configure**; Grafana **Autonomous Analysis** | [Autonomous Analysis](#autonomous-analysis) |

### Operational Intelligence Assistant

Ops Signals includes a single chat interface ("Ask Ops Signals") that routes questions across
historical cases, current findings, behaviors, analyzers, and application documentation. The
assistant should be treated as a retrieval and explanation layer, not as an oracle.

By default it runs on deterministic retrieval and template answers - no AI required. Point it at
a local model (self-hosted via Ollama, `docker compose --profile ai up`; no API key, no cloud
calls) and it additionally gets:

- LLM-synthesized answers grounded in the same retrieved evidence, instead of a fixed template
- LLM-assisted question routing on top of (never instead of) the deterministic keyword router, so
  a weaker model can only add coverage, never lose it
- Semantic search over cases, findings, and behaviors, not just keyword matching

Every response labels which mode produced it (`ai_synthesis_used`), so it's never ambiguous
whether an answer came from a model or from a template.

#### What users can expect

- Ask natural-language questions about findings, cases, signals, behaviors, analyzers, and architecture
- Retrieve relevant cases, documentation, and evidence from vector search
- Get plain-language summaries grounded in stored operational data and repo docs
- Ask follow-up questions like "what changed?", "have we seen this before?", or "what is behavior intelligence?"
- See source links, case IDs, or documentation references used in the answer

#### What users should not expect

- Guaranteed root-cause truth from the chat output alone
- Autoremediation or direct system changes
- Free-form guesses without evidence
- Answers that go beyond the stored data, docs, and retrieval context
- Replacement for the underlying analyzers, rules, or source observability tools

## Data, Automation & Configuration

How data gets in, how autonomous scanning decides what to watch, and how to tune analyzer and
behavior config.

### Data Sources

#### Prometheus

Connect Ops Signals to an existing Prometheus datasource for direct or autonomous analysis. See
[`docs/standalone-prometheus-analysis.md`](docs/standalone-prometheus-analysis.md).

One Prometheus is set with `OPS_SIGNALS_PROMETHEUS_URL`. For Grafana Mimir with several tenants (or
several Prometheus servers), list them as named connections in a file set by
`OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE` - start from
[`examples/prometheus-connections.yaml`](examples/prometheus-connections.yaml). The Configure panel and
Validate Data then get a connection picker, each autonomous policy keeps its connection, and alerts
are analysed on the tenant their labels match. Series from several clusters behind one endpoint are
analysed per cluster, and HA replica copies count once. See
[Mimir, Thanos and other multi-source backends](docs/standalone-prometheus-analysis.md#mimir-thanos-and-other-multi-source-backends).

#### CSV Input

```csv
timestamp,service,metric_name,value,env,host,namespace,pod,unit,metric_type
2026-07-12T14:00:00Z,payments-api,cpu_usage,78.2,prod,ip-10-0-1-5,,payments-7d8c9,percent,gauge
2026-07-12T14:01:00Z,payments-api,cpu_usage,84.6,prod,ip-10-0-1-5,,payments-7d8c9,percent,gauge
```

#### OTLP

Prometheus and CSV are both pull/upload - Ops Signals asks for the data. OTLP is the reverse: an
OTel SDK or Collector pushes metrics to Ops Signals: point its `otlphttp` exporter at
`http://localhost:8001/api/otlp`. See [OTLP Metrics Ingestion](#otlp-metrics-ingestion) for setup
and guardrails.

#### Deploy and change events

Your CI pipeline sends deploys, config changes and feature-flag flips to `POST /api/events` (the
**Send deploy events** tile on the Integrations page has a ready-made `curl` step). Alerts and
findings then name the change that came just before a problem. How events are joined to metrics
(service, environment, time) is in
[`docs/finding-drilldown.md`](docs/finding-drilldown.md#how-are-deploy-events-joined-to-metrics-and-findings).

### Autonomous Analysis

Autonomous analysis turns three inputs into concrete Prometheus metric jobs: monitoring intent
(categories such as performance, capacity, availability, or custom metrics), scope (environment,
service, namespace and the labels that identify them) and an execution policy (interval, analysis
window, metric budget). Metrics are discovered from Prometheus and classified by the rules in
`config/prometheus_metric_knowledge.yaml` and `config/autonomous_metric_taxonomy.yaml`, with
sampling that keeps one noisy service from crowding out the rest.

A policy runs once or on a recurring schedule, and a failing schedule is surfaced rather than going
quiet. Each run takes at most `max_metrics_per_run` metrics (default 500); the rest are excluded for
that run, not carried over, and shown as budget-limited. Jobs run one after another. Results,
coverage and history are on the **Overview** tab and in the Grafana plugin.

See [`docs/autonomous-analysis-preview.md`](docs/autonomous-analysis-preview.md) for planning,
discovery, the budget and scheduling, and
[`docs/autonomous-pipeline-architecture.md`](docs/autonomous-pipeline-architecture.md) for how it
runs.

### YAML Configuration

Configuration is layered YAML: shared settings, analyzer defaults, then provider-specific input
mapping. Operational memory (Qdrant and embeddings) is set in the root `config.yaml`. See
[`docs/configuration.md`](docs/configuration.md) for the merge order, the files and an
example.

#### Analyzer Configuration

Shared analysis mode, window, and analyzer defaults live in `config/analyzers.yaml`;
provider-specific input mapping lives in `config/providers/*.yaml`. See
[`docs/configuration.md`](docs/configuration.md) for the merge order and file layout.

#### Behavior Rules

Cross-metric behavior definitions live in `config/behavior_definitions.d/*.yml` - one file per
behavior, evaluated as facts against analyzer output. See
[`docs/behavior-intelligence.md`](docs/behavior-intelligence.md) for a full worked example.

#### Thresholds and Parameters

Per-analyzer defaults (window size, sensitivity) are set in `config/analyzers.yaml`. The Universal
Router's suitability-scoring weights are documented separately since they're heuristic, not a
threshold you tune directly - see
[`docs/analyzer-recommendation.md`](docs/analyzer-recommendation.md).

## Integrations

Ways to plug Ops Signals into tools you already use.

### Grafana Plugin

```bash
./scripts/run_grafana_stack.sh
```

That script builds the plugin bundle, starts Grafana on `3000`, Prometheus on `9090`, mock metrics, and the backend on `8002`. `8002` is reserved for the Grafana/plugin backend.

See [`docs/grafana-plugin-local-setup.md`](docs/grafana-plugin-local-setup.md) for installing the
plugin specifically, and
[`docs/grafana-plugin-feature-walkthrough.md`](docs/grafana-plugin-feature-walkthrough.md) for a
tour of Interactive Analysis and Autonomous Analysis inside Grafana.

### MCP Server

An MCP server exposes Ops Signals to MCP clients over stdio: `python -m intelligence.cli mcp`
(read-only) or `mcp-write` (adds case updates, memory indexing and the chat tools). `./scripts/test_mcp.sh` checks
it locally. Client configuration and the tool list are in [`docs/mcp-server.md`](docs/mcp-server.md).

### OTLP Metrics Ingestion

Ops Signals can receive metrics pushed directly from an OpenTelemetry SDK or an OTel Collector,
in addition to CSV upload and pull-based Prometheus queries:

```
POST /api/otlp/v1/metrics
```

Both OTLP/HTTP encodings are supported (`Content-Type: application/x-protobuf` or
`application/json`). Gauge and Sum (counter) metrics are supported; Histogram,
ExponentialHistogram, and Summary points are accepted but rejected with a `partial_success`
response, not silently dropped.

To try it without setting up a real OTel Collector, send a synthetic series and watch a finding
appear in the UI:

```bash
./scripts/run_all.sh
./scripts/send_test_otlp_metrics.py --service demo-service
```

Point `-t otlphttp` metrics in an OTel Collector config at Ops Signals like this:

```yaml
exporters:
  otlphttp:
    endpoint: http://localhost:8001/api/otlp
```

The path is `/api/otlp`, not OTLP's spec-default root path - see
[`docs/design/otlp-metrics-ingestion-plan.md`](docs/design/otlp-metrics-ingestion-plan.md#3-endpoint) for why.
Received points are buffered and analyzed on the same 60-second scheduler cycle used for
autonomous Prometheus monitoring, not per-request. The design doc covers the volume and cardinality
guardrails and the `GET /api/metrics` self-observability endpoint.

### Slack Notifications

Pushes high-importance findings to a Slack channel, so a problem that autonomous analysis finds at
03:00 doesn't wait for someone to open the UI.

1. Create a Slack incoming webhook (Slack app settings, api.slack.com/apps → Incoming Webhooks).
2. In `.env` (see `.env.example`):
   ```bash
   OPS_SIGNALS_SLACK_ENABLED=true
   OPS_SIGNALS_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
   OPS_SIGNALS_SLACK_MIN_IMPORTANCE=0.7
   ```
3. Restart the backend, then check the wiring with `./scripts/send_test_slack_finding.py`.

Only findings with importance at or above `OPS_SIGNALS_SLACK_MIN_IMPORTANCE` are posted. A broken
webhook is logged and never fails the analysis.

### Alert Enrichment (Alertmanager to Slack)

![Enriched alerts in Slack](docs/screenshots/images/slack/alert-enrichment-messages.png)

A plain alert says only that a threshold was crossed. The on-call engineer then spends the first
minutes of every page working out *what happened, what changed, and whether it's been seen before*.
Alert enrichment answers those three questions in the alert itself.

When a Prometheus rule fires, Alertmanager sends the alert to Ops Signals as an **extra** receiver
(your existing routes are untouched). Ops Signals then:

1. pulls the alerting series from Prometheus and runs the analyzers → **📈 What happened**
   ("sustained baseline shift ~621 → ~425 ms, started around 23:59 UTC"), or reuses a finding that
   autonomous analysis already produced and says how much earlier it was detected;
2. matches deploys/config changes your CI sent to `POST /api/events` → **🚀 What changed**
   ("started 7 min after deploy `v2.0.0`");
3. runs the existing alert-context lookup → **🧠 Seen before** (prior occurrences, confirmed vs
   noise, most similar resolved case and its fix);
4. posts one Slack message, clearly marked as coming from an **Alertmanager alert**, with a
   **✅ [RESOLVED]** follow-up when the alert clears.

It adds a trigger and an output around the existing pipeline, not new analysis logic. The finding
lands in the normal findings tables and the UI, and every alert is recorded in
`ops_alert_enrichments`. Status, `absent()` and log alerts skip the analysis, say why, and still get
the change and history sections. Nothing is ever dropped or hidden.

**Try it locally.** Set `OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED=true` and a Slack webhook in `.env`,
then:

```bash
./scripts/run_all.sh              # also starts a local Alertmanager + demo alert rules
./scripts/send_test_alert.py      # fire a test alert on demand (--scenario status, --deploy-minutes-ago 5, ...)
```

For a live demo with pods and deploys, run [`./scripts/demo_live.py`](docs/live-demo.md) in a second terminal.

**Connect your own Alertmanager** by adding a webhook receiver pointing at
`/api/integrations/alertmanager` with `continue: true`, pointing `OPS_SIGNALS_PROMETHEUS_URL` at the
same Prometheus, and (optionally) sending deploy events from CI. Full guide - why it matters,
architecture, Alertmanager config, per-rule annotations, Slack controls and troubleshooting:
[`docs/alert-enrichment.md`](docs/alert-enrichment.md).

## Examples

### Example Operational Finding

A finding from autonomous analysis of `http_errors_total` on the `cart` service, with drill-down on
and a deploy recorded (shortened):

```json
{
  "service": "cart",
  "metric_name": "http_errors_total",
  "title": "http_errors_total experienced a persistent baseline shift during the selected time window.",
  "summary": "A structural change was detected around sample 120, where the average value increased from 0.4197 to 3.0148, a change of 618.4%. ...",
  "category": "behavior_change",
  "health_status": "critical",
  "importance_score": 0.85,
  "investigation_priority": 1,
  "comparison_json": {
    "breakdown": {"status": "ok", "label": "pod", "spread": "partial", "parts_total": 6, "parts_changed": 2, "new_parts": 2}
  },
  "changes": {
    "status": "matched",
    "matches": [{"event_type": "deploy", "version": "v1.4.2", "minutes_before_anchor": 0.1}],
    "pods": {"status": "linked", "parts": ["cart-8c2-q1", "cart-8c2-w7"]}
  }
}
```

`category` is one of `behavior_change`, `unusual_activity`, `data_quality` or
`operational_insight`; `health_status` is `critical`, `significant` or `normal`, set by the
importance score (0.8 or more, 0.55 or more, below that). The UI shows them as **High**, **Medium**
and **Low** importance: `normal` means a change was found but it is small, not that all is well. See
[`docs/operational-findings.md`](docs/operational-findings.md). How a finding becomes a
case is in [`docs/operational-cases.md`](docs/operational-cases.md).

## Current Limitations

- Authentication is a single optional shared token, with no users or roles. Run it on a trusted
  network - see [`docs/security-model.md`](docs/security-model.md)
- No autonomous remediation
- No claim that similarity equals root-cause equivalence
- Historical retrieval depends on the quality of stored summaries and metadata
- Some memory workflows are still evolving and should be treated as operational assistance, not automation
- Analyzer recommendation scoring is deterministic and currently profile-based; it does not yet run deeper analyzer-specific probes
- Alert enrichment analyzes Prometheus-compatible alerts only (Grafana-managed and Loki alerts get
  the change and history sections), uses one Prometheus connection, and posts resolve follow-ups as
  new Slack messages rather than threads - see
  [`docs/alert-enrichment.md`](docs/alert-enrichment.md#current-limitations)
- OTLP metrics ingestion is single-instance only (no distributed queue), OTLP/HTTP only (no gRPC),
  and metrics-only (no logs/traces) - see
  [`docs/design/otlp-metrics-ingestion-plan.md`](docs/design/otlp-metrics-ingestion-plan.md#10-explicit-non-goals-phase-1)

## Roadmap

- Expand analyzer coverage
- Improve operational memory retrieval filters
- Add richer case comparison and retrieval views
- Extend evaluation datasets for regression checks
- Document release and contribution workflows more fully
- Kubernetes and cloud-provider ingestion; ITSM/automation and generic external-system consumers -
  see the explicitly-labeled roadmap section in
  [`docs/architecture.md`](docs/architecture.md#roadmap-not-yet-implemented)

## Who's Using Ops Signals?

If you're running Ops Signals somewhere - production, staging, or just evaluating it - we'd like to know. Add yourself to [ADOPTERS.md](ADOPTERS.md) via a short PR, or open an issue if a PR is more than you want to do.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

See [LICENSE](LICENSE).
