# Analyzer Library And Routing Matrix

This table lists each analyzer known to the project, the library it represents, whether that library is used in the actual runtime execution flow, why the analyzer is useful, and the official library link.

Important distinction:

- Pipeline analyzers are analyzers the current production pipeline can execute.
- Router-only analyzers are known by the analyzer router registry, but do not yet have a direct production implementation unless mapped to an existing pipeline analyzer.
- The routing algorithm itself is deterministic profile scoring. It uses extracted features such as `shift_index`, `seasonality_strength`, `trend_strength`, `spikiness`, sample count, and sampling regularity. Analyzer libraries are relevant in the runtime execution flow after routing selects what to run.

| Analyzer name | Library | Library used in realtime flow? | Why used, with example | Link of library |
|---|---|---|---|---|
| `baseline_shift` | `ruptures` with `pandas` preprocessing | Yes. `baseline_shift` is the user-facing/runtime analyzer, and it uses the real `ruptures` package for change-point detection. | Used for sustained level changes. Example: CPU average moves from 40% to 70% after a deploy, with the change point detected around the transition sample. | [ruptures](https://github.com/deepcharles/ruptures) |
| `ruptures` | `ruptures` | Implementation/library concept, not a separate user-facing production signal in the main runtime flow. Router recommendations for `ruptures` map to the `baseline_shift` pipeline analyzer. | Used as the detection engine behind baseline/regime-shift analysis. Example: latency is stable at 100 ms, then abruptly stabilizes around 250 ms after a deploy. | [ruptures](https://github.com/deepcharles/ruptures) |
| `anomaly_zscore` | Internal z-score logic using `pandas` | Yes, but it is internal logic, not ADTK/PyOD. Runtime calculates z-scores directly with `pandas`. | Used for isolated unusual values. Example: memory usage normally stays near 55%, but one short window jumps to 95%. | [pandas](https://pandas.pydata.org/docs/) |
| `trend` | `statsmodels` with `pandas` preprocessing | Yes. `trend` is the user-facing/runtime analyzer, and it uses `statsmodels` OLS regression internally. | Used for gradual directional movement. Example: disk usage grows steadily from 50% to 85% over several days, with slope, p-value, and R-squared captured as evidence. | [statsmodels](https://www.statsmodels.org/) |
| `stumpy` | `stumpy` | Yes, when dependencies are installed. Runtime calls `stumpy.stump`; the custom `numpy` fallback remains as a defensive fallback if the package is unavailable. | Used for repeated motifs or recurring patterns. Example: request traffic repeats the same daily shape every 24 hours. | [STUMPY](https://stumpy.readthedocs.io/en/latest/) |
| `prophet` | `prophet` | Optional. Runtime calls `Prophet.fit` and `predict` only if `prophet` is installed; otherwise it uses a `numpy.polyfit` fallback. | Used for forecastable metrics with trend or seasonality. Example: daily traffic follows a predictable weekly pattern, and the latest value is far above forecast. | [Prophet](https://facebook.github.io/prophet/docs/quick_start.html) |
| `trend_regression` | Regression concept; maps to `trend` analyzer | No separate runtime analyzer. Runtime maps this concept to the `trend` analyzer, which uses `statsmodels`. | Used by the router as the conceptual analyzer for linear movement. Example: queue depth increases consistently across the analysis window. | [statsmodels](https://www.statsmodels.org/) |
| `adtk` | ADTK | No. Current runtime does not call ADTK; router mapping sends ADTK-like anomaly cases to `anomaly_zscore`. | Useful for rule-based time-series anomaly checks. Example: traffic violates its usual seasonal range during one afternoon. | [ADTK](https://adtk.readthedocs.io/en/stable/) |
| `pyod` | PyOD | No. Current runtime does not call PyOD; router mapping sends PyOD-like outlier cases to `anomaly_zscore`. | Useful for outlier-centric analysis. Example: a few points are far away from the normal distribution of CPU values. | [PyOD](https://pyod.readthedocs.io/en/latest/index.html) |
| `pyod_outlier` | PyOD | Yes. Runtime uses PyOD KNN for advanced point outlier detection and emits anomaly signals. | Used for isolated anomalous points when z-score is too simple. Example: CPU has a few unusual values far from nearby operating behavior. | [PyOD](https://pyod.readthedocs.io/en/latest/index.html) |
| `darts` | Darts | No. Current runtime does not call Darts; router mapping sends Darts-like forecast cases to `prophet`. | Useful for richer forecasting, including complex or non-linear time-series patterns. Example: a metric has multiple seasonal effects and needs more expressive forecasting than a simple trend. | [Darts](https://unit8co.github.io/darts/) |
| `kats` | Kats concept; mapped to existing runtime analyzers | No direct Kats package runtime. The current Python/Numpy stack is not compatible with the published `kats` package, so router `kats` recommendations map to `baseline_shift`, `trend`, `anomaly_zscore`, `stumpy`, and `prophet`. | Useful when a metric has mixed behavior. Example: a series has a baseline shift, a trend, and recurring seasonality in the same window. | [Kats](https://github.com/facebookresearch/Kats) |
| `alibi_detect` | Alibi Detect | No. Current runtime has no direct Alibi Detect analyzer. | Useful for drift or distribution movement. Example: request latency distribution slowly changes shape even when the average does not move much. | [Alibi Detect](https://github.com/SeldonIO/alibi-detect) |
| `river` | River | No. Current runtime has no direct River analyzer and the current pipeline is batch-oriented. | Useful for online anomaly or drift detection on streaming data. Example: a live metric stream needs point-by-point anomaly scoring without retraining on the whole dataset. | [River](https://github.com/online-ml/river) |

## Recommendation

Use this table as the source of truth when deciding whether a router recommendation can execute today.

- For production execution, prefer analyzers with a real pipeline implementation.
- For router-only analyzers, either add a config-driven implementation or mark them as unsupported/roadmap-only.
- `baseline_shift` is the product/domain analyzer name. The real `ruptures` library is the implementation used underneath it for change-point detection.
