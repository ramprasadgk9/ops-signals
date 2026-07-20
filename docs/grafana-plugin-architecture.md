# Grafana Plugin Architecture

This branch reshapes the frontend into a Grafana-style plugin surface while keeping the existing Python backend as the analysis engine.

## Current Direction

- Grafana is the user entry point
- Prometheus remains the metric source
- Ops Signals receives sample data and runs analyzers
- Findings and behavior intelligence are returned as structured result objects
- The UI focuses on workflow, not a full standalone navigation shell

## Frontend Shape

- `frontend/src/plugin/` contains the plugin-oriented UI layer
- `frontend/src/plugin/OpsSignalsPlugin.tsx` is the primary entry surface
- `frontend/src/plugin/types.ts` defines the analysis contract used by the plugin shell
- `frontend/src/App.tsx` now renders the plugin surface directly
- `frontend/src/main.tsx` mounts the app without the standalone router wrapper

## Intended Grafana Flow

1. Select Prometheus datasource
2. Select service
3. Select metric
4. Select time range
5. Run analysis
6. Send samples to Ops Signals
7. Execute analyzers
8. Produce signals and findings
9. Search operational memory and behavior knowledge
10. Render results in a Grafana panel or app view

## Next Step

The next implementation step is to replace the current mock result handoff with a real Grafana datasource or backend plugin contract.
