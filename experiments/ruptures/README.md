# Ruptures Experiments

This folder contains a reusable experiment framework for exploring change-point
detection with `ruptures` across arbitrary time-series CSV datasets.

Workflow:

1. Load CSV
2. Inspect dataset
3. Plot raw signal
4. Optionally normalize
5. Run Ruptures
6. Plot detected change points
7. Compare with labels if available
8. Generate a Markdown report

The reusable logic lives in `src/`, while `configs/` contains YAML experiment
definitions. Use the notebook for exploration, not for core logic.
