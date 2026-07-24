# Ops Signals Grafana Plugin: Feature Walkthrough

This walkthrough explains what the local Grafana plugin does today, how to use each feature, and what you should expect during testing.

It is written for someone who already completed the local setup in [grafana-plugin-local-setup.md](/Users/ramprasad/Documents/workspace/github/ops-signals/docs/grafana-plugin-local-setup.md).

## Goal

The plugin is meant to help you move through this flow:

1. Choose a Prometheus metric
2. Run Ops Signals analysis
3. Review findings and evidence
4. Ask questions about the run
5. Create a case
6. Save RCA and resolution
7. Publish that case to memory for future similar-case retrieval

## Before You Start

Make sure these are running:

- Grafana on `http://localhost:3000`
- Prometheus on `http://localhost:9090`
- Ops Signals backend on `http://localhost:8000`

Make sure the plugin bundle is current:

```bash
cd frontend
npm run build:grafana
cd ..
docker compose up -d --force-recreate grafana
```

Open the plugin:

```text
http://localhost:3000/a/ops-signals-app/ops-signals
```

If the UI looks stale, hard refresh the browser.

## Screen Areas

The current plugin surface has five main areas:

- Top toolbar
- Run summary and run details
- Finding and metric timeline
- Evidence and assistant
- Investigation drawer and cases drawer

## 1. Top Toolbar

The toolbar is where you define what should be analyzed.

Fields:

- `Data source`
- `Ops Signals backend`
- `Service`
- `Metric`
- `Mode`
- `Service label`
- `Time range`

### Data source

Use this to choose the Grafana Prometheus datasource.

Expectation:

- It should list the Prometheus datasource Grafana already knows about.
- If nothing appears here, Grafana Prometheus is not configured correctly.

### Ops Signals backend

Use `Local backend (:8000)` for most local development.

Expectation:

- The backend status chip should show `Backend connected`.

### Service

This is the label value used to isolate one service from Prometheus data.

Examples:

- `sample-ec2-instance`
- `ruptures-lab`
- `trend-lab`
- `spike-lab`

Expectation:

- Local mock data should offer discovered service values once Prometheus has scraped enough samples.

### Metric

This is the Prometheus metric name or a full PromQL expression, depending on `Mode`.

Examples:

- `cpu_usage`
- `request_latency_p95`
- `error_rate`

### Mode

Use:

- `Metric` when you want to query a raw Prometheus metric name
- `PromQL expression` when you want a full custom expression

### Service label

This tells the plugin which Prometheus label identifies the service.

Default:

- `service`

Change it only if your Prometheus data uses a different label like `job`, `app`, or `service_name`.

## 2. Time Range

The plugin now has its own time-range controls.

You can use:

- `Last 30m`
- `Last 1h`
- `Last 6h`
- `Last 24h`
- Custom `From`
- Custom `To`

### Best local testing pattern

Start with:

- `Last 30m`

Why:

- it gives a focused signal window
- it avoids very old samples
- it usually gives enough points for router scoring and lightweight analyzers

Expectation:

- `Run Analysis` stays disabled if the range is invalid
- after clicking `Apply custom range`, the summary line should update

## 3. Run Analysis

Click `Run Analysis` after the toolbar is filled in.

What happens behind the scenes:

1. Grafana queries Prometheus
2. The plugin normalizes samples
3. The plugin sends samples and metadata to the backend
4. The backend profiles the time series
5. The analyzer router evaluates fitness
6. The pipeline runs analyzers allowed by the configured selection mode
7. The plugin renders the result

Expectation:

- stage messages appear while the run is executing
- after success, the page should show:
  - samples
  - signals
  - findings
  - behavior findings
  - metric timeline

## 4. Run Summary

The summary strip shows the top-level count of what happened.

You will see:

- `Samples`
- `Signals`
- `Findings`
- `Behavior Findings`

How to interpret them:

- `Samples` means points analyzed in this run
- `Signals` means analyzer-level detections
- `Findings` means higher-level operational summaries
- `Behavior Findings` means behavior-intelligence outputs

## 5. Run Details

Open `Run details` to see the execution metadata.

You should expect:

- run ID
- datasource
- datasource UID
- service
- query window
- status
- analyzer routing summary
- `Clear DB for testing`

This section is especially useful during development because it reveals:

- which analyzers actually ran
- which analyzers were only recommended
- which analyzers were optional
- which analyzers were rejected

## 6. Finding Card

If the analyzers produce a finding, the main card summarizes it.

You can:

- read the finding title and summary
- inspect importance and category
- click `Investigate`
- click `Create Case`
- click `View Evidence`

Expectation:

- if no analyzer emits a meaningful signal, the plugin will show a no-finding state instead of a finding card

## 7. Metric Timeline

This is the chart of the analyzed signal.

It shows:

- the metric line
- the baseline hint
- signal windows when available

Use it to sanity-check:

- whether the current time window really contains a visible change
- whether a detection lines up with the metric behavior you expected

## 8. Evidence

The Evidence card summarizes why the finding exists.

It includes:

- count of signal windows
- earliest signal
- highest observed value
- analyzer confidence

Click the evidence toggle to expand the compact signal table.

Expectation:

- you should see the signal analyzer names and confidence values for the current finding

## 9. Ask Ops Signals

This is the run-aware assistant surface inside the plugin.

It can answer:

- why something was detected
- which analyzers ran
- what to investigate first
- what root cause might fit
- whether similar cases exist

There are two answer modes:

- local run-grounded answers for analyzer-routing questions
- backend assistant plus vector retrieval for historical and documentation questions

Expectation:

- if a question is about routing, the answer should reflect the current run metadata
- if a question is about similar cases, the answer depends on whether cases were previously published to memory

## 10. Create Case

`Create Case` turns the current finding into an investigation case.

Behavior:

- if no case exists yet for that finding, a new one is created
- if a case already exists, it is reopened instead of duplicated

Expectation:

- the investigation drawer should open
- you should see the case number and current status

## 11. Investigation Drawer

The investigation drawer is the case workflow.

Steps:

1. `Finding`
2. `Investigation`
3. `Root Cause`
4. `Resolution`
5. `Publish Knowledge`

### Investigation

Use this step to capture notes and update investigation status.

Expectation:

- saved notes should reappear when the case is reopened

### Root Cause

Use this step to store:

- RCA status
- RCA summary
- confidence
- verified flag

Expectation:

- once filled, this becomes useful to future similar-case retrieval

### Resolution

Use this step to store:

- outcome status
- outcome summary
- corrective action

Expectation:

- resolved cases should become more useful historical references than empty cases

### Publish Knowledge

Use this step to index the case into operational memory.

Expectation:

- memory status should move toward `indexed`
- after indexing, similar-case retrieval becomes much more useful

## 12. View All Cases

This opens the cases drawer for the current service and metric.

Expectation:

- if cases exist, you should see:
  - case ID
  - title
  - status
  - updated time
  - knowledge state
- if no cases exist, the drawer should still open and explain that clearly

If clicking the button does nothing, the most common cause is stale frontend code or a backend that was not restarted after the new `/api/cases` list endpoint was added.

## 13. Clear DB For Testing

This is a development-only reset tool.

It clears:

- analysis runs
- normalized timeseries
- signals
- findings
- cases
- question answers
- case vector memory

It does not clear:

- configuration files
- app documentation memory

Use it only when you want a clean local slate.

## 14. Suggested First Demo Path

If you want a reliable first walkthrough, use this sequence:

1. Open the plugin
2. Choose `Local backend (:8000)`
3. Choose `ruptures-lab`
4. Choose `cpu_usage`
5. Set `Last 30m`
6. Click `Run Analysis`
7. Review `Run details`
8. Open evidence
9. Ask `Which analyzers ran?`
10. Click `Create Case`
11. Add RCA and resolution
12. Publish knowledge
13. Run another service and ask for similar historical cases

## 15. What Good Local Behavior Looks Like

A healthy local plugin session should feel like this:

- the toolbar fills from real Prometheus values
- the run completes without JSON or CORS errors
- the run details explain what analyzers ran
- findings map back to the visible metric shape
- the assistant can explain the run
- created cases reopen correctly
- published cases later appear in historical retrieval

## 16. Known Local Limits

- The plugin is unsigned in local development
- Similar-case quality depends on what cases you have already indexed
- Mock Prometheus data still depends on Prometheus having scraped enough recent points for the selected window
- `recommended_only` may intentionally run fewer analyzers than you expect if router scores are not strong enough
