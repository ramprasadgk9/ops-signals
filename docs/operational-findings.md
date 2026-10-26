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

## Filtering by Service

When the window has findings from two or more services, the **Findings** page shows a **Service**
dropdown next to **Sort by**. Type to search it; each service shows how many findings it has in the
window, busiest first. Picking one keeps only that service's findings and the combined patterns
(Behavior Intelligence) made from them. The charts above the list still cover the whole window.

The choice is kept in the URL (`/findings?service=payments-api`), so a filtered list can be shared.
Findings with no service (metrics without a `service` label, or OTLP data without `service.name`)
are listed together as **No service label** (`?service=(none)`). If the chosen service has nothing
in the window, the page says so and offers **Last 7 days** and **Show all services**.

The Grafana plugin's Autonomous overview has the same **Service** select next to the cluster chips;
the findings, behavior findings and cases on the overview follow it.

## Current State

This layer is implemented and used to rank and present operational issues in the UI.
