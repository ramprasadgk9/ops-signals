# UCR Anomaly Archive harness

Scores Ops Signals on the
[UCR Time Series Anomaly Archive](https://www.cs.ucr.edu/~eamonn/time_series_data_2018/) (Wu & Keogh,
"Current Time Series Anomaly Detection Benchmarks are Flawed and are Creating the Illusion of
Progress", 2021): 250 series from ECG, blood pressure, gait, respiration, insect feeding, power
demand, NASA telemetry and more, each with exactly one anomaly.

```bash
.venv/bin/python -m benchmark.run_all --suites ucr
```

The first run downloads the archive (184 MB) into `benchmark/.cache/ucr/` (gitignored), checks it
against a pinned SHA-256, and extracts only the 250 series files. Nothing from the archive is
committed and none of its code is run.

## What each series gives

The file name holds the labels: `<n>_UCR_Anomaly_<name>_<train end>_<begin>_<end>.txt`. The first
`<train end>` points are guaranteed normal, and the anomaly is `<begin>`..`<end>` (1-based). Every
method is told there's one anomaly after the training part and gives one location.

## Scoring

This harness uses the archive's own rule, from the scoring slide in the archive
(`UCR_AnomalyDataSets.pptx`). With `L = end - begin + 1`, an answer `P` is correct if
`min(begin - L, begin - 100) < P < max(end + L, end + 100)`. Accuracy is the share of the 250
series answered correctly. The report also shows the "random dart" rate the rule is designed around:
the chance that a uniformly random guess in the test part is correct.

## Methods

- **Ops Signals (product):** the production pipeline (generic provider), with the router choosing
  the analyzers. The answer is the top localized finding after the training part, ranked by
  importance score, which is the order a user sees findings in.
- **`anomaly_zscore`, `pyod_outlier`, `seasonal_anomaly`, direct:** each analyzer with its
  production configuration, on every series. The answer is its most confident localized signal.
- **Matrix-profile discord (reference):** not an Ops Signals analyzer. Each test subsequence is
  compared with every training subsequence (`stumpy`), and the answer is the one farthest from its
  nearest normal neighbour. The window is one period, estimated from the training part.
- **Largest single jump (trivial baseline):** the biggest point-to-point change in the test part.

A finding's location is its change point when it reports one, otherwise its first row. Findings
that cover half the series or more (trends, forecast fits, motif summaries) are skipped because
they don't point at a location. The product's `stumpy` analyzer reports repeated patterns
(motifs), not unusual ones, so it has no direct method here.

## Things to know when reading the results

- Most UCR anomalies are wrong shapes (a reversed beat, a slowed gait cycle), not wrong values, so
  point detectors aren't expected to do well. The discord reference shows what a subsequence method
  achieves on the same series.
- Each (series, method) run gets 600 seconds in a worker process. A run that times out or fails
  scores as no answer. Timeouts depend on the machine, so they can change the accuracy fingerprint
  between machines.
- Series have no timestamps. Each gets a synthetic one-minute timestamp, which means
  `seasonal_anomaly` checks for a "daily" cycle of 1,440 points. That has no meaning for these
  recordings, and on long series it is also what makes the product slow.
- "distorted" and "noise" series are noisier copies of other series in the archive, so they aren't
  independent samples.
