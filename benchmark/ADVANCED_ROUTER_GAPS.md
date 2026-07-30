# Advanced Router Scenario Gaps

Phase 1 validates behavior-only routing for:

- `ruptures` on pure baseline shift
- `stumpy` on pure seasonality/repeating patterns
- `trend_regression` on pure linear trend
- `pyod` and `adtk` on isolated spikes/outliers

The remaining requested analyzers need task or execution context before they can
be uniquely validated without overfitting synthetic values:

- `prophet`: Behavior overlaps with `stumpy`, `darts`, and `trend_regression`.
  The router needs an explicit forecasting task or forecast horizon to prefer
  Prophet over other seasonal/trend-compatible analyzers.
- `darts`: Behavior overlaps with Prophet for trend plus seasonality. The router
  needs a complex-forecasting task, nonlinear-model preference, or forecast
  constraint to distinguish it cleanly.
- `river`: Streaming and online anomaly detection are execution-mode choices,
  not reliably inferable from a static batch CSV. The router needs an
  `execution_mode: streaming` or online-update requirement.
- `kats`: Mixed behavior can make Kats appropriate, but it intentionally overlaps
  with Ruptures, Prophet, Darts, STUMPY, and Trend Regression. The router needs
  task intent such as "broad multi-method diagnosis" to require Kats as primary.
- `alibi_detect`: Distribution drift needs explicit `distribution_drift` or
  `drift` profile extraction. Mapping slow drift to baseline shift would hide a
  capability gap.

Suggested follow-up request shape:

```yaml
RouterRequest:
  dataframe: ...
  metric_name: cpu.usage_user
  analysis_task: forecast | motif_discovery | trend_summary | change_point | anomaly_detection | drift_detection
  execution_mode: batch | streaming
  forecast_horizon: 12h
  latency_requirement: interactive
```
