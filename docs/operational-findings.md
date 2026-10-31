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

## Example

A finding from autonomous analysis of `http_errors_total` on the `cart` service, with drill-down on
and a deploy recorded (shortened):

```json
{
  "service": "cart",
  "metric_name": "http_errors_total",
  "title": "http_errors_total experienced a persistent baseline shift during the selected time window.",
  "summary": "A structural change was detected around sample 120, where the average value increased from 0.4197 to 3.0148, a change of 618.4%. ...",
  "category": "behavior_change",
  "health_status": "critical",
  "importance_score": 0.85,
  "investigation_priority": 1,
  "comparison_json": {
    "breakdown": {"status": "ok", "label": "pod", "spread": "partial", "parts_total": 6, "parts_changed": 2, "new_parts": 2}
  },
  "changes": {
    "status": "matched",
    "matches": [{"event_type": "deploy", "version": "v1.4.2", "minutes_before_anchor": 0.1}],
    "pods": {"status": "linked", "parts": ["cart-8c2-q1", "cart-8c2-w7"]}
  }
}
```

`category` is one of `behavior_change`, `unusual_activity`, `data_quality` or
`operational_insight`; `health_status` is `critical`, `significant` or `normal`, set by the
importance score (0.8 or more, 0.55 or more, below that). The UI shows them as **High**, **Medium**
and **Low** importance: `normal` means a change was found but it is small, not that all is well.
How the card is worded from these fields is in [`finding-anatomy.md`](finding-anatomy.md); how a
finding becomes a case is in [`operational-cases.md`](operational-cases.md).

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
