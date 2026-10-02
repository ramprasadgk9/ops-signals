# Operational Findings

Operational findings are the intermediate interpretation layer between signals and cases.

## Why Findings Exist

Signals are useful, but they are still too granular for many operator workflows. Findings group evidence into a human-readable operational statement.

## What a Finding Contains

- title
- summary
- category
- health status
- importance score
- source signal references
- comparison metadata

## Role in the Workflow

```text
Signals -> Finding Aggregation -> Operational Findings -> Operational Cases
```

## Current State

This layer is implemented and used to rank and present operational issues in the UI.
