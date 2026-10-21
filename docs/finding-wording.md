# Finding wording

Finding cards (web UI, Grafana plugin) and Slack messages describe each finding in plain words:

> **Better** · Error rate dropped sharply and stayed lower
> About 11.3% until Oct 19, 10:54 PM. Since then about 1.2% (down 89%).
> **Why it matters:** Fewer requests fail, so fewer users see errors. If nobody changed anything on
> purpose, check that traffic didn't drop at the same time.
> **Happened with:** Slow-request time (p95) also dropped at Oct 19, 10:54 PM (571 ms to 357 ms).
> **What to check:** Deploys or config changes in spike-lab between Oct 19, 10:24 PM and 11:24 PM.
> ▸ Technical details

The wording comes from **`config/finding_templates.yaml`**. Change it there and save. The backend
reads the file again on the next request, so there's no need to restart it (restarting works too).

Nothing is stored. The wording is built from the finding and its signals' evidence each time a
finding is read (`backend/app/services/finding_plain.py`), so a change applies to old findings as
well. A finding's `title` and `summary` never change; they're under **Technical details**, and
alerts, cases, search and the assistant keep reading them.

## What you can change

| Section | What it does |
|---|---|
| `badges` | The badge labels: `worse`, `better`, `changed`, `gap`, `noise`, `blip`. |
| `services` | What each service does, how important it is, and the targets it's held to. See below. |
| `service_importance` | The label each importance gets on the card ("Critical service"). |
| `concepts` | One block per kind of metric (error rate, latency, CPU...): `bad_when` (`up`, `down` or `either`) decides Worse or Better, `worse` and `better` are the "Why it matters" sentences, `check` is "What to check". |
| `unknown_meaning` | The "Why it matters" sentence for a metric with no concept. Such a metric always gets the **Changed** badge, never a guess. |
| `metrics` | Per metric name: `plain_name` (what the card calls it), `concept`, `unit`. |
| `patterns` | For metrics not listed by name: regular expressions that set a `concept` or `unit`. |
| `templates` | The headline and lines for each kind of finding. |

Units: `ratio` (0.113 is shown as 11.3%), `percent`, `ms`, `s`, `bytes`, `per_second`, `count`,
`cores`. Leave `unit` out when you don't know it; values are then plain numbers (243, 0.53).

### Describe a metric

A metric nobody described reads "We don't know what this metric means for your users". To fix that,
add it under `metrics`:

```yaml
metrics:
  checkout_orders_total: {plain_name: Orders placed, concept: request_rate}
```

Or add a new kind of metric under `concepts` and point the metric at it:

```yaml
concepts:
  orders:
    bad_when: down
    worse: Fewer orders are coming in. Customers may not be able to check out.
    better: More orders are coming in.
    check: The checkout page, payment provider errors, and recent releases.
metrics:
  checkout_orders_total: {plain_name: Orders placed, concept: orders}
```

## Describe a service and its targets

With a service described, its findings say who they affect and how they stand against the target
the team holds the service to:

> **Worse** · **Critical service** · Error rate rose sharply and stayed higher
> About 0.4% until 10:00 AM. Since then about 2.1% (about 5 times as high).
> **Your target:** Above your 1% target since 10:00 AM (2 hours so far).
> **Why it matters:** More requests fail, so more users see errors or failed actions.
> **This service:** Customers pay for their orders here.

```yaml
services:
  payments:
    about: Customers pay for their orders here.
    importance: critical
    targets:
      error_rate: {below: 0.01}
      request_latency_p95: {below: 500}
  search:
    about: Customers find products here.
    targets:
      http_requests_total: {above: 100}
```

- Service names match the finding's service, ignoring case. Services that aren't listed read as
  before.
- `importance` is `critical`, `normal` or `low`. It's a label on the card and in Slack; it doesn't
  change a finding's importance score, priority or which list it's in.
- A target is per metric name: `below` for values that should stay under it (errors, latency),
  `above` for values that should stay over it (requests, free disk). Write it in the metric's raw
  value, the same number the analyzers see: an `error_rate` of 1% is `0.01`, a
  `request_latency_p95` of 500 ms is `500`.
- The target line uses the values the card already shows: the averages before and after a change,
  the two halves of a trend, a spike's peak, a forecast's actual value. It says "Above your 1% target
  since ...", "Back within your 1% target since ...", "Still within your 500 ms target" and so on.
  A data gap or a stuck value has no target line.
- An entry that isn't right (an unknown importance, a target written `{under: 0.01}`) is left out
  and logged; the rest of the service stays.

## How "Happened with" is chosen

"Happened with" points to **another finding**. When the card is shown, it looks through the other
saved findings and keeps those that pass every check:

| Check | Why |
|---|---|
| Same service | A change in another service is a different story. |
| A different metric | Another finding on the same metric is the same change found again by another run, not a second clue. |
| Both are a step change ("rose / dropped and stayed") | Only a step has one exact moment to compare. Spikes, trends, stuck values and gaps don't, so they're never matched. |
| The two changes are at most 10 minutes apart | Changes in the same few minutes often share one cause: a deploy, a restart, a traffic move. |
| The other finding was saved in the last 24 hours | Keeps the search small. |

When several findings on one metric pass, the closest in time is kept, so there's at most one line
per metric. The line itself is the other finding's `templates.level_change.related` sentence,
written with that finding's own metric name and values. The finding's Technical details don't
mention it: they describe only its own metric. On the web UI the line links to the other finding;
on both screens, hovering the "Happened with" label shows a short version of these rules.

Nothing about the link is stored. It's worked out each time the card is read, so the order of the
runs doesn't matter, and a later run that finds a closer change replaces the earlier one.

Example: spike-lab's error rate dropped from 9.1% to 0.6% at 8:15 PM. Its CPU usage dropped from 1.1
to 0.28 at 8:14 PM. The error-rate card says "Happened with: CPU usage also dropped at 8:14 PM (1.1
to 0.28)". Latency on spike-lab only had slow trends that day, so it isn't listed.

The 10 minutes and the 24 hours are `RELATED_WINDOW` and `RELATED_SEARCH` in
`backend/app/services/finding_plain.py`, not settings in the wording file. If you change the 10
minutes, change `RELATED_HINT` in `frontend/src/utils/findingPlain.ts` (the tooltip) too.

## Templates and their placeholders

Every line may also use `{plain_name}`, `{service}` and `{metric}`. A concept's lines may use only
those three.

| Template | Used when | Placeholders |
|---|---|---|
| `level_change` | A lasting step up or down (ruptures, baseline_shift) | `rose_or_dropped`, `sharply`, `higher_or_lower`, `before`, `after`, `change`, `change_time`, `window_start`, `window_end` |
| `trend` | A slow climb or fall. When the two halves of the window average within 5% of each other, the badge is **Changed** and `small` is the only line under the headline, so a 1% drift isn't called Better or Worse. | `climbing_or_falling`, `steadily_or_unevenly`, `first_half`, `second_half`, `half`, `change`, `peak`, `down_or_up` |
| `spikes` | Short bursts outside the normal range (pyod_outlier, anomaly_zscore) | `above_or_below`, `times`, `up_or_down`, `peak`, `first_time`, `last_time`, `normal_low`, `normal_high`, `duration`, `typical`, `count` |
| `odd_stretch` | A stretch unlike the rest of the series (stumpy) | `first_time`, `last_time` |
| `data_gap` | Data stopped arriving | `duration`, `first_time`, `last_time`, `missing_points`, `gap_count` |
| `flatline` | The value stopped changing | `stuck_value`, `duration`, `first_time`, `last_time`, `normal_change` |
| `forecast` | Ran away from the forecast | `higher_or_lower`, `actual`, `expected`, `off` |
| `targets` | The "Your target" line, for a service with a target on the metric | `target`, `breach_side`, `since`, `until`, `duration`, `half`, `peak`, `value` |

Times (`change_time`, `first_time`...) are shown in each reader's own time zone.

## When something is wrong

- **A placeholder that isn't on the template's list** (a typo like `{befor}`) switches that template
  off. Its findings show the stored summary, and the backend log says which template and
  placeholder: `finding_templates: template 'level_change' is switched off (unknown placeholders ...)`.
  Other templates keep working.
- **A concept line with a wrong placeholder** is left out; the rest of the card stays.
- **A file that isn't valid YAML** turns plain wording off everywhere until it's fixed, and the log
  says so. Cards show the stored title and summary, as before this feature.
- **A finding without enough evidence** (for example one saved before spike signals kept their
  normal range) shows its stored summary.

After changing the file, run the wording tests. They check the shipped file loads with every
template on, and they show what ten real findings read like:

```
.venv/bin/python -m pytest tests/test_finding_plain.py -q
```

If you changed wording on purpose, the golden texts in that test change with it. Update them.
