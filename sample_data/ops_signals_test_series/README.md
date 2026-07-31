# Ops Signals manual test datasets

All datasets contain 120 samples at 5-minute intervals using:

- `timestamp`
- `cpu_usage`

## Expected routing behavior

1. `01_ruptures_abrupt_regime_shift.csv`
   - Shape: stable high level, one abrupt persistent drop, stable low level
   - Expected primary: Ruptures
   - Trend Regression should be optional or not recommended

2. `02_trend_smooth_linear_increase.csv`
   - Shape: smooth continuous increase with low noise
   - Expected primary: Trend Regression
   - Prophet/Darts may also be recommended if eligible for forecasting

3. `03_stumpy_repeating_motif.csv`
   - Shape: repeated operational cycle
   - Expected primary: STUMPY
   - Prophet/Kats may appear as alternatives

4. `04_pyod_adtk_isolated_spikes.csv`
   - Shape: stable baseline with four isolated spikes
   - Expected primary: PyOD and/or ADTK
   - Ruptures should not be primary because values return to baseline

5. `05_kats_mixed_behavior.csv`
   - Shape: trend + repeating cycle + persistent level shift
   - Expected primary: Kats or multiple recommended analyzers
   - Ruptures, STUMPY, Trend Regression, and forecasting analyzers may appear

## What to compare in the UI

For each upload, record:

- detected profiles
- recommended / optional / rejected analyzers
- executed analyzers
- generated signal type
- finding title and summary
- signal window
- chart overlays
- explanation for why each analyzer was selected or skipped
