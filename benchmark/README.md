# Ops Signals Benchmark Foundation

This directory contains reproducible benchmark scenarios for Ops Signals. The
router benchmark suite validates analyzer routing against deterministic
time-series behaviors and uses the same shared production routing service used
by CSV upload validation.

Want to add a new scenario? See [`CONTRIBUTING.md`](CONTRIBUTING.md) for a step-by-step walkthrough.

## Run everything: the evidence report

One command runs every suite and writes a local snapshot with a detailed HTML report:

```bash
.venv/bin/python -m benchmark.run_all
```

Each run gets its own folder, and `benchmark/results/latest` points at the newest one:

```text
benchmark/results/<UTC timestamp>-<short sha>/
  report.html    open this - summary, per-scenario detail, charts, method basis, how to reproduce
  results.json   every suite's raw results plus the run manifest
  raw/           the per-scenario JSON/Markdown each individual runner writes
```

`benchmark/results/` is gitignored: snapshots stay on the machine that produced them. Keep the
ones you want as evidence; delete the rest.

The manifest records the commit (and any uncommitted changes), Python and library versions, CPU,
and SHA-256 hashes of every config and dataset used. The **accuracy fingerprint** hashes all
results except wall-clock timings, so a rerun on the same commit and data prints the same value -
that's the quick check that a result is reproducible.

Suites: `router`, `behavior`, `performance`, `nab` and `tcpd`. `nab` runs the whole Numenta Anomaly
Benchmark corpus through the production analysis path; it fetches NAB on first use and takes several
minutes; see [`nab/README.md`](nab/README.md). `tcpd` scores change-point detection on the Turing
Change Point Dataset against the 14 methods published with it; see [`tcpd/README.md`](tcpd/README.md). Run only some suites with `--suites router,behavior`. Rebuild a report from an existing snapshot,
without rerunning anything, with:

```bash
.venv/bin/python -m benchmark.report_html benchmark/results/latest/results.json
```

The command exits non-zero if any suite has a `FAIL` or `ERROR`. `GAP` doesn't fail it.

## Source datasets

Raw TSBS exports (one host, one CPU series, 5-minute resolution):

- 24-hour source: `benchmark/source-data/tsbs/healthy_cpu_24h_raw.txt`
- 7-day source: `benchmark/source-data/tsbs/healthy_cpu_7d_raw.txt`
- 30-day source: `benchmark/source-data/tsbs/healthy_cpu_30d_raw.txt`

## Directory roles

- `source-data/tsbs/` holds the immutable raw TSBS source files.
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
| `cpu_healthy_stable_v1` | Negative control: nothing recommended, no actionable finding |

Two scenarios (`cpu_pure_baseline_shift_v1` and `cpu_pure_baseline_shift_shifted_dates_v1`) also
declare an `expected_event` in their `ground_truth.yaml` - when
present, the benchmark actually runs the required analyzer and checks the produced signal's
direction, magnitude, and timing against it, not just whether the router recommended it.
`cpu_healthy_stable_v1` instead declares `expects_no_actionable_findings: true`, which runs every
real analyzer and checks that finding aggregation doesn't turn any resulting noise into a
critical/significant alert.

## Behavior Intelligence Scenario Suite

Every scenario above analyzes one metric in isolation and validates the analyzer router. Behavior
Intelligence works differently - it correlates signals across *multiple* metrics into a single
cross-metric finding (see `config/behavior_definitions.d/`) - so it needs its own kind of
scenario. These live in `benchmark/scenarios/behavior_*` and declare `expected_behavior_findings`
instead of `expected_router` in their `ground_truth.yaml`.

Run every behavior scenario:

```bash
.venv/bin/python -m benchmark.run_behavior_scenarios
```

Run one scenario:

```bash
.venv/bin/python -m benchmark.behavior_benchmark \
  --scenario benchmark/scenarios/behavior_server_slow_v1
```

| Scenario | Behavior definition | Metrics |
| --- | --- | --- |
| `behavior_server_slow_v1` | `server_slow` | `cpu_usage`, `memory_usage` |
| `behavior_latency_error_cascade_v1` | `latency_error_cascade` | `request_latency_p95`, `error_rate` |

## Performance Benchmark

Measures how long normalization and each real analyzer take as data volume grows, using the
24h/7d/30d datasets under `benchmark/normalized/` (the same ones the router benchmark's README
section above reserves for this). Report-only by design - wall-clock time isn't comparable across
machines, so there's no pass/fail threshold beyond a deliberately generous tripwire meant only to
catch a catastrophic algorithmic regression, not to enforce an SLA.

```bash
.venv/bin/python -m benchmark.performance_benchmark
```

Writes `benchmark/reports/performance_report.json` and `.md`. Note: some analyzers (stumpy in
particular, via Numba JIT compilation) pay a one-time ~6s cost on their first call in a process -
`run_all()` runs an unrecorded warm-up pass on the smallest dataset first so the recorded numbers
reflect actual data-scaling behavior instead of cold-start noise.

Regenerate scenario datasets:

```bash
for generator in benchmark/scenarios/*/generate_dataset.py; do
  .venv/bin/python "$generator"
done
```

## Commands

Normalize a TSBS source file:

```bash
.venv/bin/python benchmark/scripts/normalize_tsbs.py \
  --input benchmark/source-data/tsbs/healthy_cpu_7d_raw.txt \
  --output benchmark/normalized/healthy_cpu_7d.csv
```

Run the router benchmark for the baseline-shift scenario:

```bash
.venv/bin/python -m benchmark.router_benchmark \
  --scenario benchmark/scenarios/cpu_pure_baseline_shift_v1
```

Expected router benchmark result:

- `ruptures` is `RECOMMENDED`.
- The detected shift is an increase, at least the declared minimum magnitude, and within the
  declared timing tolerance.
- Reports are written to `benchmark/reports/cpu_pure_baseline_shift_v1_router.json` and `.md`.

Run benchmark tests:

```bash
.venv/bin/python -m pytest -q tests/test_analyzer_router_profile_matching.py tests/test_router_benchmark.py
```

## Retired scenarios

`benchmark/scenarios/_retired/` keeps scenarios that were removed from the suite, each with the
reason. The runners skip it. See [`scenarios/_retired/README.md`](scenarios/_retired/README.md).

## Assumptions

- The original TSBS files are immutable inputs and are never modified.
- The 7-day dataset is the first standard benchmark source.
- The 24-hour dataset is reserved for smoke validation.
- The 30-day dataset is reserved for future forecasting, seasonality, and scalability work.
- The router benchmark invokes `TimeSeriesRoutingService`, the same
  application-level normalization and router path used by CSV upload validation.
