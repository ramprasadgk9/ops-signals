# UI Tour

A short guide to every tab in the standalone web UI and every mode in the Grafana plugin — what
each one is for, and where to read more.

The two frontends are separate applications sharing the same backend (see
[`docs/02-architecture.md`](02-architecture.md)); a feature that exists in one does not
automatically exist in the other.

## Standalone Web UI

| Tab | Route | What it's for |
| --- | --- | --- |
| **Overview** | `/` | The landing dashboard — recent findings, case activity, and a summary of what the autonomous scheduler has found. Start here. |
| **Autonomous Analysis Configure** | `/autonomous-monitoring` | Configure which services/metrics to watch and which monitoring categories to enable, preview the resulting plan, run it once, or save it as a recurring schedule. See [`docs/autonomous-analysis-preview.md`](autonomous-analysis-preview.md). |
| **Investigations** | `/investigations` | Ad-hoc investigation view for digging into a specific metric or service outside the autonomous flow. |
| **Findings** | `/findings` | Every single-metric Finding the system has produced, searchable and filterable. Each finding's detail view names which ingestion path produced it (CSV, Prometheus, Datadog, or OTLP) and charts the raw points behind it, for tracing a finding back to what was actually ingested. See [`docs/06-operational-findings.md`](06-operational-findings.md). |
| **Cases** | `/cases` | Every Case (an investigation promoted from a Finding or Behavior Finding), with its lifecycle state, RCA, and outcome. See [`docs/07-operational-cases.md`](07-operational-cases.md). |
| **Behavior Intelligence** | `/behavior-intelligence` | Cross-metric Behavior Findings — conditions that only show up when multiple metrics are considered together. See [`docs/14-behavior-intelligence.md`](14-behavior-intelligence.md). |
| **Behavior Lab** | `/behavior-intelligence/lab` | A sandbox for testing behavior definitions against sample data before enabling them for real. |
| **Operational Memory** | `/operational-memory` | Qdrant-backed semantic search over past cases, plus the alert-context preview an external alert manager would see. See [`docs/08-operational-memory.md`](08-operational-memory.md). |
| **Ask Ops Signals** *(Beta)* | `/assistant` | Grounded conversational Q&A over cases, findings, and behaviors. See [`docs/23-ask-ops-signals-assistant.md`](23-ask-ops-signals-assistant.md). |
| **Experiments** | `/experiments` | Compares analyzer runs against each other on the same data, and is the home for the [Analyzer Workbench](#analyzer-workbench) below. |
| **New Analysis** | `/validate-data` | Upload a CSV or point at a Prometheus datasource to run a one-off analysis outside the autonomous scheduler. See [`docs/18-standalone-prometheus-analysis.md`](18-standalone-prometheus-analysis.md). |

### Analyzer Workbench

A grouping inside **Experiments**, not a separate top-level tab:

- **Labs** — one page per analyzer (Z-Score Anomaly, PyOD Outlier, Prophet Forecast, Ruptures Change
  Point, STUMPY Motif, Trend) for running that analyzer directly against sample data and inspecting
  its raw output.
- **Add Analyzer** — the guided flow for registering a new analyzer. See
  [`docs/04-analyzer-plugin-framework.md`](04-analyzer-plugin-framework.md#extensibility-model).
- **Recommendations** — the Universal Router's live recommendation preview for a given series. See
  [`docs/16-analyzer-recommendation.md`](16-analyzer-recommendation.md).

### System

**Settings** and **System** (bottom of the sidebar) cover configuration and backend/service health —
not part of the core analysis workflow, so not covered further here, with one exception: Settings'
OTLP Ingestion card shows the push endpoint URL and live received/backlog counts — the closest
equivalent to Prometheus's "Test Connection" for a push-based integration. See
[`docs/otlp-metrics-ingestion-plan.md`](otlp-metrics-ingestion-plan.md).

## Grafana Plugin

The plugin has two top-level modes, switched via tabs at the top of the app:

| Mode | What it's for |
| --- | --- |
| **Interactive Analysis** | Investigate one metric at a time — pick a Prometheus query, run analyzers against it, and inspect findings directly inside Grafana. |
| **Autonomous Analysis** | The plugin's equivalent of the web UI's Autonomous Analysis Configure + Overview, in one place: a **Configure** stage to set scope/categories and preview or save a schedule, and an **Overview** stage showing the latest run's findings, coverage details, and history. The two are reachable as a persistent tab pair once a scan has run or a schedule exists. |

Setup instructions: [`docs/grafana-plugin-local-setup.md`](grafana-plugin-local-setup.md). Feature
walkthrough: [`docs/grafana-plugin-feature-walkthrough.md`](grafana-plugin-feature-walkthrough.md).
