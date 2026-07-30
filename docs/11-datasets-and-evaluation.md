# Datasets and Evaluation

## Current Inputs

- canonical CSV samples in `sample_data/`
- deterministic router benchmark scenarios in `benchmark/scenarios/`

## What Should Be Evaluated

- ingestion correctness
- normalization consistency
- signal generation behavior
- finding aggregation quality
- case lifecycle persistence
- memory retrieval usefulness

## Evaluation Guidance

- Prefer representative samples over synthetic claims
- Compare analyzer output against known input patterns
- Treat similarity retrieval as a ranking aid, not ground truth
- Keep benchmark expectations separate from production router logic; benchmark
  comparison begins only after the shared routing service returns analyzer
  decisions.

## Current State

The repository includes deterministic router benchmark scenarios for baseline
shift, seasonality, trend, spike/outlier, seasonal forecast, complex forecast,
and mixed behavior. The benchmark suite is intentionally conservative: advanced
cases that require missing task/execution context are marked as documented gaps
rather than forced to pass by distorting data.

Run all router scenarios:

```bash
.venv/bin/python -m benchmark.run_router_scenarios
```

Run a single scenario:

```bash
.venv/bin/python -m benchmark.router_benchmark \
  --scenario benchmark/scenarios/cpu_pure_baseline_shift_v1
```

Reports are written to `benchmark/reports/` as JSON and Markdown.

Known gaps:

- `cpu_distribution_drift_v1`: requires distribution-drift profile extraction
  before `alibi_detect` can be uniquely validated.
- `cpu_online_anomaly_stream_v1`: requires an explicit router input such as
  `execution_mode=streaming` before `river` can be uniquely validated from a
  static CSV batch.
