# Analyzer Plugin Framework

## Purpose

Analyzers convert normalized time-series data into standardized signals.

## Existing Analyzer Types

- baseline shift detection
- anomaly detection
- trend analysis
- change-point / regime detection
- repeated-motif / pattern discovery
- forecasting

## Registry Model

Analyzers are registered in two places, kept deliberately separate:

- **Pipeline registry** (`config/analyzer_registry.d/*.yml`, loaded by
  `intelligence/analyzer_registry.py`) - which analyzer *implementations* exist and how to
  construct them (`class_path`, `runtime_params`). The 7 built-in analyzers live in
  `builtin.yml`; anything else in the directory is a contributor-added analyzer, loaded the same
  way. A custom registration never overrides a built-in id - registrations merge additively, so
  adding an analyzer can't silently break an existing one.
- **Router registry** (`experiments/analyzer_router/analyzer_registry.yaml`) - which analyzers
  the recommendation engine knows about and how to score them for a given metric profile
  (`supported_profiles`, `eligibility_rules`, `scoring_rules`). This is a superset of the pipeline
  registry - it also lists analyzers that are router-recommendable today but don't have a real,
  runnable implementation yet (`kats`, `darts`, `river`, `alibi_detect`, `adtk` - see
  [Router-only analyzers](analyzer-recommendation.md#router-only-analyzers-what-each-one-needs)).

These two registries are on a path to merge (`RouterSpec` in `intelligence/analyzer_registry.py`
already mirrors the router registry's field shape) but are independent today - adding a pipeline
analyzer doesn't automatically make it router-recommendable, and vice versa.

## Signal Contract

Signals should remain:

- deterministic
- explainable
- tied to the input metric and service
- traceable back to evidence

## Extensibility Model

The fastest path is the **Add Analyzer** wizard in the web UI, which walks through two tracks -
"I have Python code" (write a real `analyze()` implementation) or "I have a hosted API or model"
(Ops Signals calls your own HTTP service; see
[`http-analyzer-contract.md`](http-analyzer-contract.md)) - and three steps: Save & Validate, Test
(optional but recommended, runs against real normalized sample data), and Promote. Promoting writes
a new registration to `config/analyzer_registry.d/custom_<analyzer_id>.yml`. For the Python track
it also generates a starter adapter file at `backend/app/analyzers/custom/<analyzer_id>.py` with the
`analyze()` method stubbed out for you to fill in. The API track writes an `http:` block instead and
needs no Python file.

The manual path is the same thing without the UI (for an HTTP analyzer, see
[Registering without the UI](http-analyzer-contract.md#registering-without-the-ui) instead):

1. Implement the analyzer as an `Analyzer` subclass with an `analyze(dataframe) -> list[OperationalSignal]` method.
2. Add a `config/analyzer_registry.d/<your_file>.yml` entry with `analyzer_id`, `class_path`, and
   any `runtime_params` your constructor needs.
3. Optionally add a `router:` block (`supported_profiles`, `eligibility_rules`, `scoring_rules`)
   if this analyzer should also be recommendable by the router - see
   `experiments/analyzer_router/analyzer_registry.yaml` for the field shapes.
4. Restart the backend (or wait for `--reload` to pick up the change) - registrations are loaded
   fresh at process startup, not hot-reloaded per request.

A registered analyzer runs on CSV/interactive runs and on scheduled (autonomous) runs alike -
both build analyzers from `config/analyzer_registry.d/` through the same shared code
(`intelligence/analyzer_selection.py`) - and appears in the Recommendations view.

Give every analyzer a `description` (top level, next to `display_name`): one or two plain
sentences on what it looks for, with an example. The web UI and the Grafana plugin show it as a
tip next to the analyzer's name in results, so readers don't have to look it up. The wizard's
"What it looks for" field writes it.

Two options exist for guard-style analyzers such as a data-health check (both are also switches
in the wizard):

- `router.eligibility_rules.accepts_flat_or_gappy_series: true` - the router normally rejects a
  series for every analyzer when it is at least 95% one value, more than 30% missing, or has zero
  variance. With this set, those three checks are skipped for this analyzer only.
- `always_run: true` (top level, next to `class_path`) - runs on every analysis the router doesn't
  `REJECT` it for, outside the `max_analyzers` / `min_score` contest, so a cheap check never loses
  a slot to a higher-scoring shape analyzer.

```yaml
analyzers:
  data_health:
    display_name: Data Health
    description: "Checks whether the metric stopped reporting or got stuck at one value. Example: a metric stops updating."
    class_path: backend.app.analyzers.custom.data_health.DataHealthAnalyzer
    always_run: true
    router:
      supported_profiles: [mixed]
      eligibility_rules: {min_samples: 30, accepts_flat_or_gappy_series: true}
      scoring_rules:
        base: 0.3
        rules:
          - {metric: constant_value_percentage, gte: 95.0, add: 0.5}
```

Consider also adding a benchmark scenario - see `benchmark/CONTRIBUTING.md` - so your analyzer's
behavior is validated against a known-answer dataset instead of only checked by hand.

## Analyzer Workbench (UI)

"Analyzer Workbench" is the sidebar grouping in the web UI that holds
everything on this page in one place:

- **Labs** - one page per built-in analyzer (Z-Score Anomaly, PyOD Outlier, Prophet Forecast,
  Ruptures Change Point, STUMPY Motif, Trend) for running that analyzer directly against sample
  data and inspecting its raw signal output - useful for understanding what an analyzer actually
  does before deciding whether to route more traffic to it.
- **Add Analyzer** - the wizard described above under [Extensibility Model](#extensibility-model).
- **Recommendations** - the Universal Router's live scoring preview for a given series; see
  [`docs/analyzer-recommendation.md`](analyzer-recommendation.md).

## Current Limitations

- HTTP analyzers are called once per analysis with no automatic retry; a failed call is listed on
  that run and the next run tries again. See [`http-analyzer-contract.md`](http-analyzer-contract.md).
- The pipeline and router registries haven't merged yet, so a handful of router-recommendable
  analyzer ids have no real implementation behind them - [Router-only analyzers](analyzer-recommendation.md#router-only-analyzers-what-each-one-needs)
  lists exactly which ones and why.
- Not every question has historical similarity support yet.
