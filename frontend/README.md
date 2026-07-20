# Ops Signals

Ops Signals is a Grafana app plugin for explainable operational analysis.

## Open Ops Signals

Use this page as the launch point:

[Launch Ops Signals](http://localhost:3000/a/ops-signals-app/ops-signals)

If Grafana still shows `App not found`, use the plugin overview page as the fallback:

[Open plugin overview](http://localhost:3000/plugins/ops-signals-app?page=overview)

## What it does

- Select a datasource, service, metric, and time range
- Run the analysis workflow against the selected metric context
- Review signals, findings, and behavior reasoning in a Grafana-friendly layout

## Current status

This is a local development build.

- The plugin is unsigned
- Grafana is configured to allow loading the unsigned `ops-signals-app` plugin
- The plugin is mounted from `frontend/dist` in the local Docker Compose setup

## How to open it

1. Start Grafana with `docker compose up -d grafana`
2. Build the plugin bundle with `cd frontend && npm run build:grafana`
3. Open Grafana at `http://localhost:3000`
4. Click `Launch Ops Signals`

## Full setup guide

For beginner-friendly build, install, verify, and test steps, read:

`docs/grafana-plugin-local-setup.md`

## Notes

- The Grafana app route and local app shell use the same Ops Signals workspace component
- The plugin talks to the local backend at `http://localhost:8000` by default
