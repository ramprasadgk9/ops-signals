# TCPD harness

Scores Ops Signals' change-point detection on the
[Turing Change Point Dataset](https://github.com/alan-turing-institute/TCPD): real series where five
annotators independently marked the change points. Ops Signals is compared with the 14 methods from
[TCPDBench](https://github.com/alan-turing-institute/TCPDBench) (van den Burg & Williams, "An
Evaluation of Change Point Detection Algorithms", 2020).

```bash
.venv/bin/python -m benchmark.run_all --suites tcpd
```

The first run clones both repositories into `benchmark/.cache/` (gitignored) at pinned commits. Both
are MIT-licensed. Only their data files are read; none of their code is run. A run takes about three
minutes, most of it spent re-checking the published scores.

## Scoring is verified before it is used

The metrics in `metrics.py` are ported from TCPDBench, with its license notice kept. Every run:

1. Recomputes all 1,014,504 published scores in TCPDBench's summaries from the published change
   points, and records the number of mismatches (0 at the pinned commits).
2. Reproduces the paper's published univariate averages from its per-series scores (binseg F1
   0.698, cover 0.672; zero F1 0.645, cover 0.566).

Both results are shown in the report.

## What is compared

- **Series:** the paper's univariate evaluation set (32 series: everything except the multivariate
  series, the five quality-control series and `uk_coal_employ`), limited to the 25 that ship as data.
  The other 7 are built by TCPD's download scripts, which this harness doesn't run. Every method is
  averaged over the same series.
- **Published methods:** the paper's "default" experiment, where each method uses its default
  parameters with no per-series tuning. That is the fair comparison for Ops Signals' default
  configuration. A failure scores 0 on that series, as in the paper.
- **Ops Signals, product:** the production pipeline (generic provider). The router decides whether
  a change-point analyzer runs. Change points come from `ruptures` and `baseline_shift` signals.
- **Ops Signals, direct:** `ruptures` with its production configuration, run on every series. This
  measures the detector without routing.

## Things to know when reading the results

- Both change analyzers report at most one change point per series, the primary shift, by design.
  On series with several annotated change points, recall is capped.
- TCPD's metrics reward silence on series without a change: "zero", which never predicts one,
  averages F1 0.645. Beating "zero" is the first bar.
- With 25 series, differences of a few hundredths are within noise.
- Each series gets a synthetic daily timestamp so every row maps to one resampled bucket. TCPD scores
  by row, so the dates don't matter.
