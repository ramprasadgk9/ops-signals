# ADR-001: Canonical Timeseries Contract

## Status

Accepted

## Context

The platform ingests time-series data from multiple sources and needs one downstream contract.

## Decision

Use a canonical CSV-based time-series contract that normalizes provider-specific differences before analysis.

## Consequences

- simpler analyzer input
- predictable storage schema
- easier evaluation against sample data
