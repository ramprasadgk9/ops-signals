# Ruptures Experiment Report: rds_cpu_utilization_cc0c53

## Dataset
- Rows: 4032
- Columns: 2
- Timestamp column: timestamp
- Value column: value
- Sampling interval: 0 days 00:05:00

## Configuration
- Algorithm: pelt
- Model: l2
- Penalty: 5
- Min size: 10
- Jump: 1
- Normalization: No normalization is applied. This is usually fine when the absolute metric scale is meaningful and stable.

## Validation
- OK: True

## Results
- Execution time: 21.641s
- Detected change points: [1881, 3080, 3090, 3523, 3644, 3745, 3886, 3939]

## Plots
- raw: experiments/ruptures/plots/rds_cpu_utilization_cc0c53_raw.png
- change_points: experiments/ruptures/plots/rds_cpu_utilization_cc0c53_change_points.png
- comparison: experiments/ruptures/plots/rds_cpu_utilization_cc0c53_comparison.png

## Observations
- Normalization strategy: none
- Ruptures returned 7 internal change points.
- Penalty increases usually reduce the number of detected change points and favor broader, more stable shifts.
- Penalty decreases usually increase sensitivity, which can reveal smaller regime changes but also more false positives.
- Use l2 when baseline mean shifts matter most, rbf when shape/nonlinear distribution changes matter, and normal when variance changes matter too.
- Use PELT when you want a scalable penalized search, Binary Segmentation for quick iterative splits, and Bottom Up when you want merge-based segmentation over many small pieces.

## Recommended Configuration
- Dataset: rds_cpu_utilization_cc0c53
- Algorithm: pelt
- Model: l2
- Penalty: 5
- Suitable for: operational metrics with repeatable regime changes such as CPU, latency, request rate, memory, and network throughput
- Not suitable for: highly irregular series, sparse event logs, or signals with severe missingness without preprocessing
