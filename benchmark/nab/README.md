# NAB harness

Runs the whole [Numenta Anomaly Benchmark](https://github.com/numenta/NAB) corpus (58 series,
116 labeled anomaly windows) through the same analysis path a CSV upload takes, and scores the
result against NAB's labels.

```bash
.venv/bin/python -m benchmark.run_all --suites nab
```

The first run clones NAB into `benchmark/.cache/nab` (gitignored) at the pinned commit
`ea702d75cc2258d9d7dd35ca8e5e2539d71f3140`. Only NAB's `data/` and `labels/` are read; none of NAB's
code is imported or run. NAB is MIT-licensed as of that commit. The run takes several minutes and
uses every CPU core but one.

## What runs

Each series goes through the production path with the `generic` provider: validation,
normalization, the analyzer router, the analyzers it selects (`recommended_threshold`: the top 3
above 0.80, plus `data_health`), and importance scoring. Two inputs are set per series, the way a
user would set them on upload:

- The resampling interval is the series' median sampling interval. The generic default of 5m would
  leave 11 of every 12 buckets empty on NAB's hourly series.
- Negative values are allowed, because one artificial series has them.

Series with timestamp gaps over the provider's limit are analyzed anyway, as the product now does
by default (`gap_policy: warn`). With the old reject-on-gap behavior, 18 of the 58 series were
refused before analysis.

## Two modes

**Replay (causal).** A trailing window of up to 2,016 rows is analyzed every 12 new rows, the way a
scheduled production run works. An alarm lands on the row where that run happens: the first
moment the event could have been known. An event alarms once. A later run re-detecting it (same
analyzer and signal type, start within 12 rows) stays quiet unless it is more confident. This
follows NAB's rule that a detector only uses data up to the point it is scoring, and it is the
mode behind the report's headline.

**Batch.** The whole series is analyzed at once and the alarm lands where the detected event
starts. Detectors see data after the alarm, which NAB doesn't allow, so batch shows the analyzers'
offline ceiling. It isn't comparable with NAB's published scores.

A signal's alarm score is the signal's confidence. Signals that span a whole analysis window,
like a trend or a forecast fit, never alarm in replay mode and land in NAB's unscored
probationary period in batch mode.

## Metrics

`metrics.py` computes plain window metrics using NAB's conventions where they overlap:

- The first `min(floor(0.15 × rows), 750)` rows are NAB's probationary period, and alarms there
  are ignored.
- A window is detected when any alarm falls inside it. Later alarms in the same window are
  neither rewarded nor penalized.
- Every alarm outside all windows is a false alarm.

The report's headline uses a confidence threshold of 0.5, fixed before scoring and not tuned. It
also shows every threshold in `metrics.THRESHOLDS`.

These metrics are not NAB's official score. NAB's score also rewards detecting early in a window
and applies three cost profiles. To get it, each run writes NAB-format files (`timestamp, value,
anomaly_score, label`) for both detectors, `opsSignalsReplay` and `opsSignalsBatch`, under
`<snapshot>/raw/nab_results/`, in the layout NAB's scorer reads from its `results/` directory.
Running NAB's scorer means running NAB's own code, which this harness deliberately does not do.
Doing that is a separate, explicit step.
