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

The backend uses capabilities and analyzer metadata to decide what analysis is available for a given question and service context.

## Signal Contract

Signals should remain:

- deterministic
- explainable
- tied to the input metric and service
- traceable back to evidence

## Extensibility Model

To add a new analyzer:

1. Implement the analyzer logic.
2. Emit standardized signal records.
3. Register its capability metadata.
4. Ensure it appears in the relevant question routing path.

## Current Limitations

- Analyzer coverage is intentionally narrow
- Not every question has historical similarity support yet
