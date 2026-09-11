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
  `benchmark/ADVANCED_ROUTER_GAPS.md`).

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
"I have Python code" (write a real `analyze()` implementation) or "I want to call an API"
(HTTP-backed, config-only for now - execution support is planned, see Current Limitations) - and
three steps: Save & Validate, Test (optional but recommended, runs against real normalized sample
data), and Promote. Promoting writes a new registration to
`config/analyzer_registry.d/custom_<analyzer_id>.yml` and, for the Python track, generates a
starter adapter file at `backend/app/analyzers/custom/<analyzer_id>.py` with the `analyze()`
method stubbed out for you to fill in.

The manual path is the same thing without the UI:

1. Implement the analyzer as an `Analyzer` subclass with an `analyze(dataframe) -> list[OperationalSignal]` method.
2. Add a `config/analyzer_registry.d/<your_file>.yml` entry with `analyzer_id`, `class_path`, and
   any `runtime_params` your constructor needs.
3. Optionally add a `router:` block (`supported_profiles`, `eligibility_rules`, `scoring_rules`)
   if this analyzer should also be recommendable by the router - see
   `experiments/analyzer_router/analyzer_registry.yaml` for the field shapes.
4. Restart the backend (or wait for `--reload` to pick up the change) - registrations are loaded
   fresh at process startup, not hot-reloaded per request.

Consider also adding a benchmark scenario - see `benchmark/CONTRIBUTING.md` - so your analyzer's
behavior is validated against a known-answer dataset instead of only checked by hand.

## Current Limitations

- HTTP-backed analyzers can be registered (config-only) but not executed yet - the adapter that
  would call out to an external service isn't implemented (see `AnalyzerRegistrationError` in
  `intelligence/analyzer_registry.py`).
- The pipeline and router registries haven't merged yet, so a handful of router-recommendable
  analyzer ids have no real implementation behind them - `benchmark/ADVANCED_ROUTER_GAPS.md`
  tracks exactly which ones and why.
- Not every question has historical similarity support yet.
