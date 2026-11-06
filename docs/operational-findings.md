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
- when the problem started and ended (`event_start`, `event_end`), and whether it was still going
  at the end of the analyzed data (`ongoing`)
- the problem it belongs to (`problem_id`): the first finding of the problem, shared by every later
  run that sees it again

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

## Finding states: from found to over

A finding is still happening, over, or still going when its data ended. Its state also says which
list it's in (Needs attention or Context only), how many runs saw it, and what your team answered.
Each run that sees a problem again saves a new finding with the same `problem_id`; earlier
findings are never changed, so the start, every sighting and the end all stay in the history.

**Is it still going on?** The timing chip on the card says:

| Chip | When |
| --- | --- |
| Started 09:40 · still happening | The newest finding says `ongoing`, and its data is from the last 2 hours |
| Started 09:40 · still going when the data ended (10:00) | `ongoing`, but the data is older, such as an uploaded file |
| 09:40–09:45 · over | The data went on after the last bad reading (`ongoing` is false) |

A problem that is over also says so under the headline: "Normal again since 09:45" for a spike,
"Data has been arriving again since 10:12" for a data gap, "Changing again since 10:12" for a stuck
value. The details and the Slack message use the same sentence.

**Which list is it in?** Needs attention or Context only, from its
[evidence badge](finding-trust.md). A problem that needed attention moves to Context only one hour
after it ended, with the **Over** badge; the hour keeps it in view for the people on shift. The
Overview counts, the shift handoff and `ops_signals_active_findings` follow the same lists. See
[when a problem is over](finding-trust.md#when-a-problem-is-over).

**How often was it seen?** "Seen in N runs" counts the findings of one problem. The problem is
counted once everywhere. Slack posts when a problem is new or gets worse, not on every run.

**What did your team do?** "Was this real?" keeps the team's answer: Real problem, Not a problem
or Expected change. A case on the problem stays open until someone closes it, even after the
problem is over; a closed case takes the problem out of the Overview counts.

**How long is it listed?** The Findings page and the Overview show the findings created in the
chosen window (24 hours by default; **Last 7 days** shows a week). Older findings stay in the
database and in any case made from them.

An example: checkout latency data stops at 09:40 and comes back at 10:12, with a run every 10
minutes.

| Run | Finding | Card says | List |
| --- | --- | --- | --- |
| 09:45 | #101, starts the problem | Started 09:40 · still happening | Needs attention |
| 09:55, 10:05 | #102, #103, same problem | still happening · Seen in 3 runs | Needs attention |
| 10:15 | #104, same problem | 09:40–10:12 · over, "Data has been arriving again since 10:12" | Needs attention |
| after 11:12 | later runs add findings only while the gap is in their window | the same | Context only, **Over** |

**Level changes** are over when the level comes back near where it was before the jump. Their
checks look at the level up to the last reading, so their findings always say still going; instead,
after each run, Ops Signals compares that run's latest readings with the level before and after the
jump. Latency at 200 ms that jumps to 1.8 s at 07:30 and comes back at 11:30 reads "Latency rose
sharply for 4 hours, then came back. About 200 ms until 07:30, then about 1.8 s. Back to about
200 ms since 11:30", and moves to Context only at 12:30. A level only partly back says "Partly
back: about 700 ms since 11:30" and stays in Needs attention. See
[when a problem is over](finding-trust.md#when-a-problem-is-over).

Trends ("has been climbing") don't move to Over yet.

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
