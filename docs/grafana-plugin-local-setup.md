# Ops Signals Grafana Plugin: Local Setup Guide

This guide explains how to build, install, verify, and test the Ops Signals Grafana app plugin on your local machine.

It assumes you are new to Grafana plugins and want a predictable local path first.

## What You Are Running

The local setup has three moving parts:

- `Grafana` runs at `http://localhost:3000`.
- `Prometheus` runs at `http://localhost:9090`.
- `Ops Signals backend` runs at `http://localhost:8000`.
- `Ops Signals plugin` is built into `frontend/dist` and mounted into Grafana by Docker Compose.

The plugin is an app inside Grafana. It is not published to the Grafana plugin catalog, so Grafana will show it as unsigned. That is expected for local development.

## Architecture

```text
Grafana
  |
  | opens the Ops Signals app plugin
  |
  +-- Prometheus datasource
  |     Used as the metric datasource selected by the user
  |
  +-- Ops Signals backend
        Used for services, metrics, analysis runs, findings, cases, RCA,
        resolution, and operational memory
```

For the current local flow, Grafana queries Prometheus through its configured datasource. The plugin then sends normalized samples and nonsecret query metadata to the Ops Signals backend at:

```text
http://localhost:8000
```

## Prerequisites

Install these before starting:

- Docker Desktop
- Node.js and npm
- Python virtual environment for the backend
- The Ops Signals repository checked out locally

From the repository root, confirm you are in the right place:

```bash
pwd
```

Expected path:

```text
/Users/ramprasad/Documents/workspace/github/ops-signals
```

## 1. Start The Backend

Start the Ops Signals backend on port `8000`.

Use the backend command you normally use for this repository. For example:

```bash
uvicorn backend.app.main:app --reload --port 8000
```

Verify the backend is reachable:

```bash
curl http://localhost:8000/health
```

If your backend does not expose `/health`, verify one known API endpoint instead:

```bash
curl http://localhost:8000/api/services
```

Expected result:

```text
You should receive JSON instead of a connection error.
```

## 2. Build The Grafana Plugin

From the repository root:

```bash
cd frontend
npm install
npm run build:grafana
cd ..
```

This creates the Grafana plugin bundle in:

```text
frontend/dist
```

The important files are:

- `frontend/dist/plugin.json`
- `frontend/dist/module.js`
- `frontend/dist/README.md`
- `frontend/dist/img/`

## 3. Start Grafana

From the repository root:

```bash
docker compose up -d --force-recreate grafana prometheus mock-metrics
```

Grafana runs at:

```text
http://localhost:3000
```

Prometheus runs at:

```text
http://localhost:9090
```

The Docker Compose setup mounts:

```text
frontend/dist -> /var/lib/grafana/plugins/ops-signals-app
```

That means every time you change plugin code, you should rebuild the plugin and restart Grafana.

## 4. Verify Grafana Sees The Plugin

Check plugin settings from your terminal:

```bash
curl -u admin:admin http://localhost:3000/api/plugins/ops-signals-app/settings
```

Expected result:

```text
The response should include "id":"ops-signals-app" and "enabled":true.
```

You can also verify the mounted plugin files inside the Grafana container:

```bash
docker exec ops-signals-grafana sh -lc 'ls -la /var/lib/grafana/plugins/ops-signals-app'
```

Expected files:

```text
plugin.json
module.js
README.md
img
```

## 5. Verify Local Prometheus Test Data

This repository now includes a tiny synthetic metrics target for local testing.

It exposes these Prometheus metrics:

- `cpu_usage`
- `request_latency_p95`
- `error_rate`
- `ops_signals_test_cpu_usage`

And it emits service label values like:

- `sample-ec2-instance`
- `checkout`
- `payments`
- `test-ruptures-abrupt-regime-shift`
- `test-trend-smooth-linear-increase`
- `test-stumpy-repeating-motif`
- `test-pyod-adtk-isolated-spikes`
- `test-kats-mixed-behavior`

Verify the mock target directly:

```bash
curl http://localhost:9101/metrics
```

Verify Prometheus is scraping it:

```bash
curl "http://localhost:9090/api/v1/label/service/values"
```

Expected result:

```text
You should see sample-ec2-instance, checkout, payments, and the test-* replay services.
```

Verify one metric query:

```bash
curl "http://localhost:9090/api/v1/query?query=cpu_usage"
```

Expected result:

```text
You should get time series back for the local test services.
```

Verify the replayed manual-test metric:

```bash
curl "http://localhost:9090/api/v1/query?query=ops_signals_test_cpu_usage"
```

Expected result:

```text
You should get one series per CSV file in sample_data/ops_signals_test_series.
```

## 6. Open The Plugin

Open Grafana:

```text
http://localhost:3000
```

If prompted, use the local default credentials:

```text
Username: admin
Password: admin
```

Then open the Ops Signals app route:

```text
http://localhost:3000/a/ops-signals-app/ops-signals
```

If the browser shows old UI, hard refresh:

```text
Mac: Cmd + Shift + R
Windows/Linux: Ctrl + Shift + R
```

## 7. Select The Backend And Run Analysis

In the Ops Signals app toolbar:

- `Data source`: choose a configured Prometheus datasource from Grafana.
- `Ops Signals backend`: choose `Local backend (:8000)`.
- `Service`: choose or type a service label value discovered from Prometheus.
- `Metric`: choose or type a Prometheus metric name.
- `Mode`: use `Metric` for raw metric names, or `PromQL expression` for a full query.
- `Service label`: use the label that identifies services in your Prometheus data, usually `service`, `service_name`, `job`, or `app`.
- `Time range`: use the built-in quick presets like `Last 30m`, `Last 1h`, `Last 6h`, or enter `From` and `To` directly in the plugin.
- Click `Run Analysis`.

For the sample data path, a useful test is:

```text
Data source: Prometheus
Ops Signals backend: Local backend (:8000)
Service: test-ruptures-abrupt-regime-shift
Metric: ops_signals_test_cpu_usage
Service label: service
Mode: Metric
Time range: Last 30m
```

Expected result:

```text
Grafana should query Prometheus first. Then the page should show samples, signals, findings, a metric timeline, evidence, suggested questions, and investigation actions.
```

For the five replayed CSV datasets, use these values:

- `Metric`: `ops_signals_test_cpu_usage`
- `Service label`: `service`
- `Mode`: `Metric`
- `Service`: `test-ruptures-abrupt-regime-shift`
- `Service`: `test-trend-smooth-linear-increase`
- `Service`: `test-stumpy-repeating-motif`
- `Service`: `test-pyod-adtk-isolated-spikes`
- `Service`: `test-kats-mixed-behavior`

Timing guidance:

- wait for about `30 minutes` of live Prometheus scraping before judging a full run
- use `Last 30m` to capture one complete replay of a 120-point CSV
- use `Last 10m` to `Last 15m` if you only want a partial warm-up check
- avoid absolute timestamps from `July 30, 2026` in the plugin because Prometheus stores these datasets at scrape time, not at their original CSV times

## 8. Plugin Features And How To Use Them

This section describes the current local plugin features, what they depend on, and what you should expect to see.

### Toolbar And Run Analysis

Purpose:

- Choose the metric source, backend, service, metric, and time window.
- Run one analysis pass from Prometheus into Ops Signals.

Prerequisites:

- Grafana is up on `http://localhost:3000`
- Prometheus is up on `http://localhost:9090`
- Ops Signals backend is up on `http://localhost:8000`
- The selected Prometheus datasource is working inside Grafana

How to use it:

1. Open `http://localhost:3000/a/ops-signals-app/ops-signals`
2. Set `Data source` to your Grafana Prometheus datasource
3. Set `Ops Signals backend` to `Local backend (:8000)`
4. Choose a `Service`
5. Choose a `Metric`
6. Pick `Last 30m` first for local testing
7. Click `Run Analysis`

What to expect:

- The page will show a loading stage such as Prometheus query, normalization, and analyzer execution.
- After success you should see sample count, signal count, findings, behavior findings, and a metric timeline.

### Time Range Control

Purpose:

- Run the plugin independently from hidden Grafana header controls.

How to use it:

1. Click `Last 30m`, `Last 1h`, `Last 6h`, or `Last 24h`
2. Or enter a local `From` and `To`
3. Click `Apply custom range`

What to expect:

- `Run Analysis` stays disabled if `From` is later than `To`
- The summary line updates to show the currently active range

Local testing recommendation:

- Start with `Last 30m`
- Use a current live window relative to `Thursday, July 30, 2026`
- Do not expect older absolute dates to act like live replayed data

### Run Details And Analyzer Routing

Purpose:

- Explain what the backend ran and what the analyzer router recommended

Prerequisites:

- The backend must return analyzer routing metadata
- `config/analyzers.yaml` controls selection mode such as `all`, `recommended_only`, or `manual_override`

What to expect:

- `Run details` shows run ID, datasource, service, query window, and status
- It also shows:
  - executed analyzers
  - recommended analyzers
  - optional analyzers
  - not recommended analyzers
  - rejected analyzers

Interpretation:

- `Recommended` means the router thinks the analyzer strongly fits this time series
- `Optional` means the analyzer may help but is not the best first choice
- `Rejected` means eligibility or data-shape checks failed

### Findings, Evidence, And Timeline

Purpose:

- Show the main operational finding and the supporting signal windows

How to use it:

1. Review the main finding card
2. Click `View Evidence`
3. Inspect the metric timeline and evidence summary

What to expect:

- If analyzers emit signals, you should see at least one finding or signal window
- If no analyzers emit a signal, the plugin shows a no-finding state and the routing summary still helps explain why

### Ask Ops Signals

Purpose:

- Answer questions using run context, analyzer routing, saved cases, and indexed application documentation

Prerequisites:

- Backend assistant API is running
- Case memory must be indexed if you want historical case retrieval

How to use it:

1. Click a quick prompt such as `Which analyzers ran?`
2. Or type a custom question in `Ask anything about this run...`
3. Click `Ask`

What to expect:

- Analyzer-routing questions are answered directly from the current run
- Broader questions use the backend assistant and vector retrieval when available
- If historical memory is weak or empty, the answer may fall back to application documentation

Important note:

- Similar-case answers are only meaningful when at least one prior case was created and published to memory

### Create Case And Investigation Drawer

Purpose:

- Convert a finding into an operational case and capture investigation state

Prerequisites:

- At least one finding must exist in the current run

How to use it:

1. Click `Create Case`
2. Review the drawer steps:
   - `Finding`
   - `Investigation`
   - `Root Cause`
   - `Resolution`
   - `Publish Knowledge`
3. Save notes, RCA, and resolution fields as you work

What to expect:

- Reopening the same finding should reopen the existing case instead of creating duplicates
- The drawer should show saved notes, RCA fields, resolution text, and memory status

### View All Cases

Purpose:

- Show recent saved investigations for the current service and metric

Prerequisites:

- At least one case has been created in the backend database

How to use it:

1. Click `View all cases`
2. Review the `Recent Cases` drawer
3. Click `Open case` on the one you want

What to expect:

- If cases exist, the drawer lists case ID, title, status, updated time, and knowledge state
- If no cases exist, the drawer still opens and explains that no cases were found

### Publish Knowledge

Purpose:

- Push the current case into operational memory for later retrieval by similar-case search

Prerequisites:

- A case exists
- Qdrant or the configured vector store is available

How to use it:

1. Open a case drawer
2. Go to `Publish Knowledge`
3. Click `Republish knowledge`

What to expect:

- `memory_status` should move toward `indexed`
- Future assistant questions can retrieve this case as historical evidence

### Clear DB For Testing

Purpose:

- Reset local operational run data and case vector memory during development

Prerequisites:

- Testing only
- You are okay deleting local analysis outputs and saved cases

How to use it:

1. Open `Run details`
2. Click `Clear DB for testing`
3. Confirm the browser prompt

What to expect:

- Analysis runs, normalized timeseries, signals, findings, cases, and question answers are deleted
- Case vector memory is cleared
- Application documentation memory is not cleared

Warning:

- This is destructive for local test data
- Do not use it as a production workflow

## 9. Test The Investigation Flow

After analysis finishes:

1. Review the primary finding card.
2. Click `View Evidence` to expand compact signal evidence.
3. Click one suggested question to call the backend question API.
4. Click `Create Case` to create or reopen an investigation case.
5. In the drawer, review the five lifecycle steps.
6. Add an investigation note and click `Save Case`.
7. Open `Root Cause`, add a summary, and click `Save Case`.
8. Open `Resolution`, add an outcome and corrective action, and click `Save Case`.
9. Open `Publish Knowledge` and click `Republish knowledge` when memory indexing is available.

Expected result:

```text
The drawer should update from backend responses and show the latest case status, notes, RCA, resolution, and memory state.
```

## 10. Common Problems

### Plugin Does Not Appear

Rebuild the plugin and recreate Grafana:

```bash
cd frontend
npm run build:grafana
cd ..
docker compose up -d --force-recreate grafana prometheus mock-metrics
```

Then check:

```bash
curl -u admin:admin http://localhost:3000/api/plugins/ops-signals-app/settings
```

### Browser Shows Old UI

Grafana and the browser can cache plugin bundles.

Use:

```text
Cmd + Shift + R
```

Also confirm `frontend/plugin.json` has a new version number and rebuild.

### Backend Is Not Connected

Confirm the backend is running:

```bash
curl http://localhost:8000/api/services
```

If Grafana is running in Docker and cannot reach your host backend, try the dropdown option:

```text
Host backend from Docker
```

### Invalid Plugin Signature

This is expected for local development.

The plugin is unsigned because it is not published to grafana.com. The local Docker Compose setup allows this plugin ID:

```text
ops-signals-app
```

### App Route Shows Not Found

Check that Grafana sees the app include:

```bash
curl -u admin:admin http://localhost:3000/api/plugins/ops-signals-app/settings
```

Look for:

```text
"includes"
```

The app route should be:

```text
http://localhost:3000/a/ops-signals-app/ops-signals
```

### View All Cases Does Nothing

If the button appears clickable but nothing happens:

1. Rebuild the plugin
2. Recreate Grafana
3. Hard refresh the browser
4. Restart the backend so the `/api/cases` list endpoint is active

Commands:

```bash
cd frontend
npm run build:grafana
cd ..
docker compose up -d --force-recreate grafana
uvicorn backend.app.main:app --reload --port 8000
```

Expected result:

```text
The button should open a Recent Cases drawer even if no cases exist.
```

## 11. Development Loop

Use this loop after changing plugin frontend code:

```bash
cd frontend
npm run build:grafana
cd ..
docker compose up -d --force-recreate grafana
```

Then hard refresh the browser.

## 12. Current Local Limitations

- The plugin is unsigned.
- The plugin uses Grafana's frontend datasource APIs for Prometheus access.
- The Ops Signals backend receives normalized metric samples and nonsecret query metadata.
- The app still has a local backend selector for development environments.
- Similar-case answers depend on having previously indexed cases.
- Local mock Prometheus data is only useful after Prometheus has scraped enough fresh samples for the chosen time window.
