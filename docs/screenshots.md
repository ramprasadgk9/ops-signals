# Screenshot Gallery

Ops Signals can be used through two complementary experiences:

- A standalone operational intelligence Web UI for CSV uploads, direct Prometheus analysis, OTLP metrics ingestion, findings, cases, behavior intelligence, operational memory, and assistant retrieval.
- A Grafana plugin that fits into existing Grafana and Prometheus workflows and sends selected metric data to the Ops Signals backend analysis pipeline.

The screenshots below show the current product surfaces for an early developer preview. They are intended to help first-time users understand the workflow before running the project locally.

They're recorded from the [one-command demo](demo.md) with a few extra sample services added, so
every number in them is real analyzer output. To regenerate them after a UI change, see
[Refreshing these screenshots](#refreshing-these-screenshots).

## Standalone Web Application

The standalone Web UI is the primary operational workspace. It is designed around investigation flow: start with data, review findings, create cases, preserve knowledge, and retrieve prior context.

### Overview Dashboard

The Overview dashboard summarizes operational health, active findings, open investigations, behavior intelligence, memory status, and recent activity.

![Ops Signals Overview](screenshots/images/web/01-overview.png)

### New Analysis - CSV Upload

Users can upload, validate, preview, and analyze CSV time-series data through the standalone workflow.

![CSV Analysis](screenshots/images/web/02-new-analysis-csv.png)

### New Analysis - Direct Prometheus

Users can connect to Prometheus, select or enter a metric query, preview the returned series, choose a time window, and run analysis.

![Direct Prometheus Analysis](screenshots/images/web/03-new-analysis-prometheus.png)

### Operational Findings

Findings show severity, confidence, evidence, affected services, timestamps, and operational explanations generated from analyzer output.

![Operational Findings](screenshots/images/web/04-findings.png)

### Case Investigation

Findings can be promoted into cases where users capture investigation notes, root cause analysis, resolution, and reusable operational knowledge.

![Case Investigation](screenshots/images/web/05-case-details.png)

### Behavior Intelligence

Behavior intelligence combines related signals and metrics to identify higher-level operational patterns.

![Behavior Intelligence](screenshots/images/web/06-behavior-intelligence.png)

### Operational Memory

Completed investigations can be preserved as searchable operational knowledge and reused in future investigations.

![Operational Memory](screenshots/images/web/07-operational-memory.png)

### Operational Assistant

The assistant answers grounded questions using findings, cases, behavior intelligence, operational memory, and project documentation. It is a retrieval and explanation layer, not an autonomous general-purpose AI agent.

![Operational Assistant](screenshots/images/web/08-assistant.png)

### Analyzer Recommendation

Select a stored sample and Ops Signals profiles it the same way a real analysis run does, then shows which analyzers fit its behavior (here, an abrupt regime shift: ruptures and kats), which are optional, and which don't fit, with the evidence behind each.

![Analyzer Recommendation](screenshots/images/web/09-analyzer-recommendation.png)

## Alert Enrichment in Slack

When a Prometheus alert fires, Alertmanager sends it to Ops Signals, which posts one message answering what happened (the analyzers' reading of the alerting series), what changed (deploys near the change point), and whether it has been seen before (similar resolved cases and how they were fixed). There's no page for this in the UI: the Slack message is the output. See [`alert-enrichment.md`](alert-enrichment.md).

The demo's enriched alert, as rendered by the demo's Slack stand-in:

![Enriched alert from the demo](screenshots/images/slack/enriched-alert-demo.png)

The same messages in a real Slack workspace, including a status alert that skips analysis but still gets the change and history sections:

![Enriched alerts in Slack](screenshots/images/slack/alert-enrichment-messages.png)

## Grafana Plugin

The Grafana plugin lets users analyze metrics without leaving Grafana by using:

- An existing Grafana data source
- Prometheus metrics
- The current Grafana time range
- The same Ops Signals backend analysis workflow

### Plugin Home

The plugin home provides the entry point for running Ops Signals analysis from inside Grafana.

![Grafana Plugin Home](screenshots/images/grafana-plugin/00-home-page.png)

### Prometheus Metric Selection

Users select a data source, service or metric, query, and Grafana time range before analysis.

![Grafana Prometheus Selection](screenshots/images/grafana-plugin/01-prometheus-selection.png)

### Analysis Results

Users can review detected changes, analyzer results, findings, and summarized operational insights within Grafana.

![Grafana Analysis Results](screenshots/images/grafana-plugin/02-metrics-analysis.png)

### Finding Details

Users can inspect supporting evidence, analyzer output, severity, confidence, and operational explanations from the analysis flow.

![Grafana Finding Details](screenshots/images/grafana-plugin/03-case-flow.png)

### Recent Cases

Creating a case from a finding opens its investigation workflow alongside the recent investigations connected to prior findings and operational memory.

![Grafana Recent Cases](screenshots/images/grafana-plugin/04-recent-cases.png)

### Ask Ops Signals

Users can ask grounded questions from the Grafana plugin while staying connected to the same Ops Signals backend.

![Grafana Ask Ops Signals](screenshots/images/grafana-plugin/05-ask-ops-signals.png)

### Autonomous Analysis

The plugin's Autonomous mode configures which services, namespaces, and monitoring categories to watch, then runs the plan once or on a schedule.

![Grafana Autonomous Analysis](screenshots/images/grafana-plugin/06-autonomous-analysis.png)

## Typical Workflow

1. Upload CSV data or query Prometheus.
2. Preview and validate the time series.
3. Run the analyzer pipeline.
4. Review generated findings.
5. Create an investigation case.
6. Record investigation notes, root cause, and resolution.
7. Publish the completed case to Operational Memory.
8. Retrieve related knowledge through the Operational Assistant.
9. Optionally run analysis directly within Grafana.
10. When an alert fires, get what happened, what changed, and seen before in Slack.

## Refreshing these screenshots

All of them are recorded by a script, so they can be refreshed after a UI change instead of
retaken by hand:

```bash
docker compose -f docker-compose.demo.yml up -d
./scripts/demo_smoke_test.py
./scripts/record_screenshots.sh
```

The script adds the extra sample services on top of the demo (`demo/screenshots/seed_showcase.py`),
then drives each screen in a headless browser (`demo/screenshots/capture.cjs`). The Grafana plugin
screens also need the development stack's Grafana, Prometheus, and mock metrics
(`docker compose up -d grafana prometheus mock-metrics`); set `SKIP_GRAFANA=1` to record only the
web and Slack screens.

## Learn More

- [README](../README.md)
- [Standalone Overview API](17-standalone-overview-api.md)
- [Standalone Prometheus Analysis](18-standalone-prometheus-analysis.md)
- [Release Process](13-release-process.md)
