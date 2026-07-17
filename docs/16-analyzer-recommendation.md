# Analyzer Recommendation

The Analyzer Recommendation page evaluates a selected metric sample against the existing analyzers.

## Flow

1. Select a stored metric sample.
2. Load the sample profile.
3. Score each supported analyzer deterministically.
4. Group the analyzers into recommended, conditional, and not recommended.

## Current behavior

- Uses the existing normalized time-series data.
- Reuses the existing analyzer IDs: `trend`, `baseline_shift`, `anomaly_zscore`, `stumpy`, and `forecasting`.
- Does not rely on LLM output for scores.
- Falls back to deterministic profile-based scoring when richer analyzer probes are not available yet.

## API

- `GET /api/metric-analyzer-recommendations/metrics`
- `POST /api/metric-analyzer-recommendations/evaluate?service=...&metric_name=...&analysis_run_id=...`

## UI

Open `Analyzer Rec` in the top navigation to review sample metrics and analyzer recommendations.

