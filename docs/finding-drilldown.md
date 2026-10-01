# Finding Drill-down

A finding says *what* changed at service level: "checkout errors rose 308% at 14:08". Drill-down
adds *where* it came from: "91% of the increase comes from pod checkout-x2, 1 of 6 pods". It also
says whether the change is in one pod, a few, or all of them. The service-level finding looks the
same in each case, but the response differs:

| Spread | Usually means | Likely next step |
|---|---|---|
| **Concentrated** (one pod) | a bad node, disk or instance | check that pod; a rollback is probably not needed |
| **Partial** (a few pods) | something those pods share | check what they have in common (node, zone, version) |
| **Partial or concentrated, all new pods** | a rollout in progress | compare the new version with the old one |
| **Widespread** (most pods) | code, config, traffic or a shared dependency | look at recent changes or dependencies |

![Finding drill-down: the error increase came from two new pods, pointing to a rollout](screenshots/images/web/10-finding-drilldown.png)

Drill-down is **off by default**. It runs for **autonomous Prometheus runs** and for
**alert-triggered analysis** ([`alert-enrichment.md`](alert-enrichment.md)), using the alert's query.

## Where it shows

- **Web UI**: a scope chip on finding cards ("1 of 6 pods"; hover for the pods, click for
  details) and a "Where the change came from" section in the finding details.
- **Slack alert messages**: a "📍 Where" line in the "What happened" section, with the same
  sentence and next step as the UI.
- **Grafana plugin**, Autonomous Analysis: the same chip on Related Symptoms and in the findings
  lookup, and the same section in the finding's evidence panel.

Both use the same wording (`frontend/src/utils/findingBreakdown.ts`).

## Turning it on

```bash
OPS_SIGNALS_DRILLDOWN_ENABLED=true
```

| Setting | Default | Meaning |
|---|---|---|
| `OPS_SIGNALS_DRILLDOWN_ENABLED` | `false` | Turn drill-down on |
| `OPS_SIGNALS_DRILLDOWN_LABELS` | `pod,instance` | Labels to split by, tried in order; the first that gives at least 2 parts is used |
| `OPS_SIGNALS_DRILLDOWN_MAX_FINDINGS` | `3` | Most findings per job to drill into (most important first) |

## How it works

1. An autonomous job runs as usual: one service-level query, the analyzers, findings saved.
2. For each of the job's top findings, the same PromQL is run again with the label added to its
   grouping, e.g. `sum by (service) (...)` becomes `sum by (service, pod) (...)`.
3. The finding's signals set the window. A change point (ruptures, baseline_shift) splits the series
   into before and after. An anomaly is compared with the stretch just before it.
4. Each pod's average before and after is compared, and the result is stored in the finding's
   `comparison_json.breakdown`.

Nothing else on the finding changes: title, summary, importance score and priority are exactly as
the analyzers produced them. If the per-pod query fails, the finding is still saved and the
breakdown records why.

## Two modes

- **share**, for counts and rates (`sum`/`count` queries). Pod values add up to the service value,
  so each pod gets a share of the total change, and the shares sum to 100%.
- **changed_parts**, for latency percentiles, averages, maxima and CPU %. Pod values don't add up,
  so a percentage share would be misleading. Instead the breakdown shows which pods changed and by
  how much, compared with their own normal level.

In both modes, **spread is judged by how far each pod moved from its own normal level, not by its
share**. Pods carry different amounts of traffic. If every pod's errors double, the busiest pod
still holds the biggest share of the increase, and a share-based rule would wrongly call that
"concentrated".

A pod with no data before the change, or fewer than 3 points, is marked **new**, for example a pod
started by a rollout. The "fewer than 3" part matters because a change point often lands a scrape
or two after a rollout's new pods come up.

## When there is no breakdown

The finding shows "Breakdown by pod not available" and the reason:

| Reason | Meaning |
|---|---|
| `no_change_time` | No single moment to compare around, e.g. a slow trend |
| `query_shape_not_supported` | The query isn't one of the shapes the planner builds (`AGG by (...) (...)`, `histogram_quantile(q, sum by (le, ...) (...))`) |
| `single_part` | Only one pod or instance reports the metric |
| `too_many_parts` | More series than `OPS_SIGNALS_PROMETHEUS_MAX_SERIES` |
| `query_failed` | Prometheus returned an error |
| `not_enough_baseline` / `no_data` / `no_net_change` | Not enough per-pod data to say anything |

Data-health findings ("stopped reporting", "flatline") never get a breakdown, because they are
about the data, not the service's behavior.

## Accuracy

`python -m benchmark.drilldown_benchmark` runs 990 synthetic cases (results go to the gitignored
`benchmark/reports/drilldown/`). The cases cover one, two, all or new pods changing; both modes;
3, 6 and 12 pods; 2%, 10% and 25% noise; and 1.5×, 3× and 10× changes, with pods at different
normal levels.

| Situation | Right pods ranked first | Right spread |
|---|---|---|
| One pod | 100% | 100% |
| Two pods | 100% | 100% |
| All pods | 100% | 100% |
| New pods | 98.9% | 91.1% |

**Known limit:** with a small change (1.5×), a new pod can land within the normal variation
between existing pods. Drill-down then reports only the more extreme new pod as moved
("concentrated" instead of "partial"). Every miss in the run above is a new-pods case with a
1.5× change.

Synthetic cases test the arithmetic, not real clusters. Real pods also differ in load balancing,
restarts and scrape gaps.

## Limits

- Prometheus autonomous runs only. CSV, OTLP, manual Prometheus ingestion and the plugin's
  Interactive Analysis don't have it yet.
- Slack messages don't include the breakdown yet, because they are sent before drill-down runs.
- Each drill-down is one or two extra range queries per finding, capped by
  `OPS_SIGNALS_DRILLDOWN_MAX_FINDINGS` and by the existing Prometheus series and sample limits.
