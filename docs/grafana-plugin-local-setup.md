# Ops Signals Grafana Plugin: Local Setup Guide

This guide explains how to build, install, verify, and test the Ops Signals Grafana app plugin on your local machine.

It assumes you are new to Grafana plugins and want a predictable local path first.

## What You Are Running

The local setup has three moving parts:

- `Grafana` runs at `http://localhost:3000`.
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

For the current local flow, the plugin talks to the Ops Signals backend at:

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
docker compose up -d --force-recreate grafana
```

Grafana runs at:

```text
http://localhost:3000
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

## 5. Open The Plugin

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

## 6. Select The Backend And Run Analysis

In the Ops Signals app toolbar:

- `Data source`: choose `Prometheus`.
- `Ops Signals backend`: choose `Local backend (:8000)`.
- `Service`: choose a service returned by the backend.
- `Metric`: choose a metric returned for that service.
- `Time range`: use `Last 14 days` for now.
- Click `Run Analysis`.

For the sample data path, a useful test is:

```text
Service: sample-ec2-instance
Metric: cpu_usage
```

Expected result:

```text
The page should show samples, signals, findings, a metric timeline, evidence, suggested questions, and investigation actions.
```

## 7. Test The Investigation Flow

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

## 8. Common Problems

### Plugin Does Not Appear

Rebuild the plugin and recreate Grafana:

```bash
cd frontend
npm run build:grafana
cd ..
docker compose up -d --force-recreate grafana
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

## 9. Development Loop

Use this loop after changing plugin frontend code:

```bash
cd frontend
npm run build:grafana
cd ..
docker compose up -d --force-recreate grafana
```

Then hard refresh the browser.

## 10. Current Local Limitations

- The plugin is unsigned.
- The time range selector currently shows `Last 14 days` in the app UI.
- The current local plugin flow gets analysis data from the Ops Signals backend.
- A more Grafana-native future step is to query Prometheus through Grafana and send those samples to the Ops Signals backend for analysis.

