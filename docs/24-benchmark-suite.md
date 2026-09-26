# Benchmark Suite

Full details live in [`benchmark/README.md`](../benchmark/README.md) (how to run each suite) and
[`benchmark/CONTRIBUTING.md`](../benchmark/CONTRIBUTING.md) (how to add a new scenario). This page
is a short overview of what exists and why, for readers going through the numbered docs in order.

## Why It Exists

A synthetic scenario with a known, deliberately-injected answer is the only way to grade whether
the analysis is actually correct - real production data never comes with a verified answer key
attached. Every scenario in this suite is built backwards from a known answer for exactly that
reason.

## What's Covered

- **Router accuracy** - does the analyzer router recommend the right analyzer for a given
  time-series behavior (baseline shift, seasonality, trend, spikes, forecast patterns)?
- **Detection accuracy** - when a scenario declares a known event (direction, magnitude, timing),
  the benchmark actually runs the analyzer and checks what it found against that answer, not just
  whether the right analyzer got picked.
- **False-positive behavior** - a negative-control scenario with genuinely stable, boring data,
  validating that the system stays quiet instead of manufacturing alerts. This is where a real,
  confirmed finding lives: individual analyzers do produce some raw statistical noise on flat
  data (expected - e.g. a nonzero contamination rate), but finding aggregation correctly filters
  it out before it becomes a user-facing alert.
- **Router precision** (opt-in) - beyond "is the required analyzer present," an opt-in
  `strict_precision` check catches unexpected extra analyzers also getting recommended.
- **Behavior Intelligence** - every other scenario analyzes one metric in isolation; behavior
  scenarios use multiple correlated metrics to validate the cross-metric reasoning layer described
  in [Behavior Intelligence](14-behavior-intelligence.md).
- **Performance/scale** - report-only timing of normalization and analyzer execution as data
  volume grows (24h/7d/30d), not a pass/fail gate (wall-clock time isn't comparable across
  machines).
- **Ask Ops Signals documentation answers** - known-answer questions checking that the assistant
  cites the right file and section and that its answer contains the passage that answers the
  question. See [Ask Ops Signals: Assistant Architecture](23-ask-ops-signals-assistant.md#quality-benchmarking).

## What's Not Covered Yet

Assistant answers built from findings, cases and behaviors have no automated benchmark - the
golden questions cover documentation answers only.
