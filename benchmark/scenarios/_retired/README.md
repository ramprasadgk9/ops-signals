# Retired scenarios

Scenarios here are kept for history only. The suite runners skip this directory (it has no
`ground_truth.yaml` of its own), so nothing in here is run or reported.

## `cpu_baseline_shift_v1`

Retired 2026-09-27. The scenario injects a +15 step at the midpoint of the healthy TSBS 7-day CPU
series and expects an increase at `2016-01-04T12:00:00Z`. The source series is not flat, though:
its 12-hour means fall from about 58 to about 16 over the first three days, then climb back to about
55. That natural swing is larger than the injected step, so change-point detection correctly
reports the bigger, real drop (-36.6% at `2016-01-01T17:05:00Z`) and the scenario fails on direction
and timing. The fault is in the test data, not the detector.

`cpu_pure_baseline_shift_v1` and `cpu_pure_baseline_shift_shifted_dates_v1` cover the same case on
a flat base, so the injected shift is the only change in the series.
