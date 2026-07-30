# Ops Signals Benchmark Foundation

This directory contains reproducible benchmark scenarios for Ops Signals. The
router benchmark suite validates analyzer routing against deterministic
time-series behaviors and uses the same shared production routing service used
by CSV upload validation.

## Source datasets

- 24-hour source: `benchmark/one-host-one-cpu-24h-5m.txt`
- 7-day source: `benchmark/one-host-one-cpu-7d-5m.txt`
- 30-day source: `benchmark/one-host-one-cpu-30d-5m.txt`

`benchmark/one-host-one-cpu-24h.txt` remains untouched as an older extra file and is not used by the benchmark flow.

## Directory roles

- `source-data/tsbs/` documents the immutable TSBS source location.
- `normalized/` stores generated normalized CSV outputs.
- `scenarios/<scenario_id>/` stores generated scenario datasets, generators, and ground truth.
- `reports/` stores JSON and Markdown benchmark reports written by the runner.
- `scripts/` contains the reproducible benchmark runner.

Each scenario directory contains:

- `generate_dataset.py`: deterministic dataset generator
- `dataset.csv`: Prometheus-style benchmark CSV (`timestamp,value,metric,hostname`)
- `ground_truth.yaml`: expected router behavior and detected-profile assertions

## Router Scenario Suite

Run every router scenario:

```bash
.venv/bin/python -m benchmark.run_router_scenarios
```

Run one scenario:

```bash
.venv/bin/python -m benchmark.router_benchmark \
  --scenario benchmark/scenarios/cpu_pure_baseline_shift_v1
```

The suite prints:

```text
Scenario | Expected Recommended | Actual Recommended | Actual Optional | Result
```

Result meanings:

- `PASS`: required recommendations and detected-profile checks passed.
- `FAIL`: the router result contradicted ground truth.
- `ERROR`: dataset/configuration/parsing/router execution failed.
- `GAP`: scenario documents a known router capability gap, such as missing
  distribution-drift extraction or streaming execution context.

Current scenarios:

| Scenario | Primary expectation |
| --- | --- |
| `cpu_pure_baseline_shift_v1` | `ruptures` |
| `cpu_pure_baseline_shift_shifted_dates_v1` | `ruptures`, independent of absolute dates |
| `cpu_pure_seasonality_v1` | `stumpy` |
| `cpu_linear_trend_v1` | `trend_regression` |
| `cpu_isolated_spikes_v1` | `pyod` and/or spike/outlier analyzers |
| `cpu_seasonal_forecast_v1` | `prophet` |
| `cpu_complex_forecast_v1` | `darts` |
| `cpu_mixed_behavior_v1` | `kats` |
| `cpu_distribution_drift_v1` | `GAP`: drift profile extraction is not yet implemented |
| `cpu_online_anomaly_stream_v1` | `GAP`: router has no streaming execution-mode input yet |

Regenerate scenario datasets:

```bash
for generator in benchmark/scenarios/*/generate_dataset.py; do
  .venv/bin/python "$generator"
done
```

## Commands

Normalize a TSBS source file:

```bash
python -m benchmark.scripts.tsbs_benchmark normalize --dataset 7d
```

Generate the first scenario:

```bash
python -m benchmark.scripts.tsbs_benchmark generate-scenario
```

Run the first benchmark end to end:

```bash
python -m benchmark.scripts.tsbs_benchmark run
```

Run the 24-hour smoke path:

```bash
python -m benchmark.scripts.tsbs_benchmark smoke
```

Run the router benchmark for the baseline-shift scenario:

```bash
python -m benchmark.router_benchmark \
  --scenario benchmark/scenarios/cpu_baseline_shift_v1
```

Expected router benchmark result:

- `ruptures` is `RECOMMENDED`.
- `prophet` and `river` may be `OPTIONAL` without failing the benchmark.
- `stumpy` is not `RECOMMENDED`.
- Reports are written to `benchmark/reports/cpu_baseline_shift_v1_router.json` and `benchmark/reports/cpu_baseline_shift_v1_router.md`.

Run benchmark tests:

```bash
.venv/bin/python -m pytest -q tests/test_analyzer_router_profile_matching.py tests/test_router_benchmark.py
```

## Assumptions

- The original TSBS files are immutable inputs and are never modified.
- The 7-day dataset is the first standard benchmark source.
- The 24-hour dataset is reserved for smoke validation.
- The 30-day dataset is reserved for future forecasting, seasonality, and scalability work.
- The router benchmark invokes `TimeSeriesRoutingService`, the same
  application-level normalization and router path used by CSV upload validation.
