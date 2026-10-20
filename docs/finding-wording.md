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

## Templates and their placeholders

Every line may also use `{plain_name}`, `{service}` and `{metric}`. A concept's lines may use only
those three.

| Template | Used when | Placeholders |
|---|---|---|
| `level_change` | A lasting step up or down (ruptures, baseline_shift) | `rose_or_dropped`, `sharply`, `higher_or_lower`, `before`, `after`, `change`, `change_time`, `window_start`, `window_end` |
| `trend` | A slow climb or fall | `climbing_or_falling`, `steadily_or_unevenly`, `first_half`, `second_half`, `half`, `change`, `peak`, `down_or_up` |
| `spikes` | Short bursts outside the normal range (pyod_outlier, anomaly_zscore) | `above_or_below`, `times`, `up_or_down`, `peak`, `first_time`, `last_time`, `normal_low`, `normal_high`, `duration`, `typical`, `count` |
| `odd_stretch` | A stretch unlike the rest of the series (stumpy) | `first_time`, `last_time` |
| `data_gap` | Data stopped arriving | `duration`, `first_time`, `last_time`, `missing_points`, `gap_count` |
| `flatline` | The value stopped changing | `stuck_value`, `duration`, `first_time`, `last_time`, `normal_change` |
| `forecast` | Ran away from the forecast | `higher_or_lower`, `actual`, `expected`, `off` |

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
