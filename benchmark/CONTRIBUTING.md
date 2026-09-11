# Adding a Benchmark Scenario

This is a walkthrough for adding a new scenario to the benchmark suite. See `benchmark/README.md`
for how to *run* the suites - this doc is about *authoring* a new one.

There are two kinds of scenario. Pick the one that matches what you're validating:

| | Router scenario | Behavior scenario |
| --- | --- | --- |
| Validates | Analyzer routing/recommendation, and optionally detection accuracy | Behavior Intelligence cross-metric correlation |
| Metrics | One | Two or more |
| Runner | `benchmark.router_benchmark` / `run_router_scenarios` | `benchmark.behavior_benchmark` / `run_behavior_scenarios` |
| Ground truth key | `expected_router:` | `expected_behavior_findings:` |

Both kinds live side by side in `benchmark/scenarios/<scenario_id>/` - the runners tell them
apart by which top-level key is present in `ground_truth.yaml`, not by directory naming, though by
convention behavior scenarios are prefixed `behavior_*`.

## The golden rule: verify empirically, don't guess

Every scenario in this suite is built backwards from a known answer - you can only grade a test
if you already know what "correct" looks like. That means **write your ground truth by running the
real code and observing what it actually does, not by predicting what you think it should do.**
Guessed ground truth has caused real problems in this suite before: `cpu_pure_baseline_shift_v1`
originally forbade nothing beyond `stumpy`/`prophet`, so when `kats` and `alibi_detect` started
appearing as `optional` recommendations, nothing caught it - not because those extra
recommendations were wrong, but because nobody had checked. Run your scenario, look at the actual
output, and *then* decide what should be asserted.

## Router scenario walkthrough

1. Create `benchmark/scenarios/<your_scenario_id>/`.
2. Write `generate_dataset.py` - deterministic (seed your RNG), writes `dataset.csv` with columns
   `timestamp,value,metric,hostname`. Copy an existing one (e.g.
   `benchmark/scenarios/cpu_pure_baseline_shift_v1/generate_dataset.py`) as a starting point -
   they're all short, ~30 lines.
3. Run it: `.venv/bin/python benchmark/scenarios/<your_scenario_id>/generate_dataset.py`.
4. See what the router actually does with it, before writing any expectations:
   ```bash
   python3 -c "
   from pathlib import Path
   from benchmark.router_benchmark import run_router
   recs, profile, normalized = run_router(Path('benchmark/scenarios/<your_scenario_id>'))
   print('recommended:', [r['analyzer'] for r in recs['recommended']])
   print('optional:', [r['analyzer'] for r in recs['optional']])
   print('detected_profiles:', profile.get('detected_profiles'))
   "
   ```
5. Write `ground_truth.yaml` from what you just observed:
   ```yaml
   scenario:
     id: <your_scenario_id>
     name: <human-readable name>
     description: >
       What this scenario is testing and why.

   dataset:
     scenario_dataset: benchmark/scenarios/<your_scenario_id>/dataset.csv
     metric: <metric name>
     interval: 5m

   expected_router:
     required_recommended: [...]      # must appear in the RECOMMENDED bucket
     forbidden_recommended: [...]     # must NOT appear in the RECOMMENDED bucket
     allowed_optional: [...]          # permitted (not required) in the OPTIONAL bucket
     required_detected_profiles: [...]  # optional
     forbidden_detected_profiles: [...] # optional
     strict_precision: true           # optional, see below
   ```
6. Optional deeper checks - only add these if you actually need them, and only after confirming
   empirically that the analyzer produces what you expect:
   - **`strict_precision: true`** - fails the scenario if ANY analyzer beyond
     `required_recommended ∪ allowed_optional` shows up in either the recommended or optional
     bucket. Off by default because retrofitting it onto an untuned scenario just bakes in
     whatever noise the router happens to produce today as permanent "correct" behavior - turn it
     on once you've verified the actual output is exactly what you want, not before.
   - **`expected_event:`** - actually runs the required analyzer and checks the produced signal's
     direction, magnitude, and timing, not just whether it was recommended. Only works today for
     analyzers with a real implementation that reports `percent_change` + `change_point_index` in
     their evidence (`ruptures`, `baseline_shift`) - see `evaluate_detection_accuracy()` in
     `benchmark/router_benchmark.py`. Fields: `type`, `direction` (`increase`/`decrease`),
     `timestamp`, `tolerance_before`, `tolerance_after`, `minimum_magnitude`.
   - **`expects_no_actionable_findings: true`** - for negative-control scenarios. Runs every real
     analyzer and checks that finding aggregation never turns the result into a
     critical/significant alert. Individual analyzers producing raw statistical noise is fine and
     expected (see `cpu_healthy_stable_v1`'s ground truth notes for why); what matters is whether
     that noise survives into something user-facing.
7. Run the actual benchmark and confirm it passes:
   ```bash
   .venv/bin/python -m benchmark.router_benchmark --scenario benchmark/scenarios/<your_scenario_id>
   ```
8. If you want this scenario to actually gate CI (fail the build on a regression, not just show up
   informationally), add its id to the list in
   `tests/test_router_benchmark.py::test_router_suite_runner_returns_success_for_phase_one_scenarios`.
   Otherwise it's still discovered and reported by `run_router_scenarios.py`, just not a hard gate.

## Behavior scenario walkthrough

Same directory/generator pattern, with three differences:

1. **The CSV can (and should) contain multiple metric names** - one row per metric per timestamp,
   sharing the `hostname` column so they're understood as the same host/service. See
   `benchmark/scenarios/behavior_server_slow_v1/generate_dataset.py` for a working example with
   two interleaved metrics.
2. **Read the actual behavior definition first**, in `config/behavior_definitions.d/*.yml`. Your
   synthetic data has to satisfy its exact `inputs` (which metrics, which analyzers) and
   `conditions` (which facts, e.g. `cpu.anomaly.present == true`) - guessing at this rather than
   reading the YAML directly is how you end up debugging why nothing matched.
3. **Ground truth uses `expected_behavior_findings:`, not `expected_behavior:`.** The latter key is
   already used by router scenarios for something unrelated - a `dominant:` list describing profile
   *shape* (e.g. `[seasonal, trend]`), not which Behavior Intelligence definition should fire. This
   collision is real, not hypothetical: it was caught during development when router scenarios
   started silently showing up in the behavior suite's output.
   ```yaml
   scenario:
     id: <your_scenario_id>
     name: <human-readable name>
     description: >
       Which behavior definition this is meant to trigger, and how.

   dataset:
     scenario_dataset: benchmark/scenarios/<your_scenario_id>/dataset.csv
     metrics: [<metric_a>, <metric_b>]
     interval: 5m

   expected_behavior_findings:
     required_matched: [<definition_id>]
     forbidden_matched: [<any definition your data has no business triggering>]
   ```
4. Verify empirically before locking anything in:
   ```bash
   .venv/bin/python -m benchmark.behavior_benchmark --scenario benchmark/scenarios/<your_scenario_id>
   ```
5. Add it to `tests/test_behavior_benchmark.py` if you want CI coverage (the whole suite is
   CI-gated today via `test_suite_runner_passes_for_all_behavior_scenarios`, so a new scenario
   under `behavior_*` with a working `expected_behavior_findings` block is covered automatically
   once discovered).

## Reports

Both benchmark runners write JSON + Markdown reports to `benchmark/reports/` - this directory is
gitignored (see its history: a test used to write a machine-specific tmp path into a tracked
report file on every local `pytest` run). If you're writing a test that calls `run_benchmark(...)`
directly, pass `reports_dir=tmp_path / "reports"` so it doesn't write into your real, local
`benchmark/reports/` directory as a side effect of running the test suite.
