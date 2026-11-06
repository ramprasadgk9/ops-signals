# Finding trust: how much to trust a finding

Every finding says how often findings like it turned out to be real, and which ones need your
attention. The numbers are measured, not guessed. This page explains what you see, where the
numbers come from, and what they don't promise. [How a finding becomes a card](finding-anatomy.md)
shows where trust fits next to the card's wording.

## What you see

The Findings page has two lists:

- **Needs attention**: findings with evidence that they usually mean something changed.
- **Context only** (folded): single unusual values, patterns and forecasts. They aren't alerts.
  In tests, they were real about as often as an alert raised at a random moment would be. They are
  useful when you're already investigating something.

Each finding carries a badge:

| Badge | Meaning | In tests |
| --- | --- | --- |
| **Strong evidence** | Two different checks agree: the values look unusual **and** the level moved and stayed there | 98% real, against 61% for a random alert (248 checked) |
| **Moderate evidence** | One check saw the level move and stay there | 67% real, against 56% for a random alert (503 checked) |
| **Data problem** | The metric stopped reporting or froze at one value | A fact, not a guess, so no rate |
| **Context only** | A single unusual value, a pattern, a trend or a forecast | Spikes were real 60% of the time, the same as a random alert |
| **Over** | It needed attention, and ended more than an hour ago | Not a rate: the data shows it ended |

Findings in "Needs attention" show two columns side by side:

- **On your service**: how many findings like this, on this service, your team said were real.
  Until there are 5 "Real problem" or "Not a problem" answers it shows how many there are so far
  ("2 of 5 answers"); after that it shows your team's own rate. "Expected change" answers don't
  count either way. A finding whose metric has no service label (shown as `unknown`) says
  **On this metric** instead: its answers are counted per metric, so answers on one unlabeled
  metric don't decide another's. Adding a service label (Prometheus `job`/`service`, OpenTelemetry
  `service.name`) gives it a per-service number.
- **Seen before**: whether past cases (detected or imported from postmortems) look like this
  finding, the closest one and what fixed it. "See past cases" opens the finding's details there.
  The column is hidden when past cases can't be searched (operational memory off).

The tested rate ("In testing": how often findings like this were real on public test data, and
what a random alert would have scored) is on the evidence badge's tooltip and in the finding's
details. It still decides the badge and which list a finding goes to.

## When a problem is over

A problem that is over leaves Needs attention one hour after it ended, and moves to Context only
with the **Over** badge. Until then it stays in Needs attention, so the people on shift still see
it, and its card already says it ended ("Data has been arriving again since 10:12").

- **Over** means the latest analysis saw data after the problem's last bad reading. A data gap is
  over when data arrives again, a stuck value when it changes again.
- If a later run sees the problem again, it is back in Needs attention.
- Nothing is deleted or changed: every run's finding, "Seen in N runs", your answers and any case
  stay. Over is not closed: a case on it stays open until someone closes it.
- The same rule decides the Overview's Needs attention count, the shift handoff and the
  `ops_signals_active_findings` metric.
- Only data problems and spikes move to Over. Level changes and trends don't yet: their checks
  look at the level up to the last reading, so a finding with one stays where it is, even when a
  spike on top of it ended.

## "Was this real?"

Every finding has three answers:

- **Real problem**: counts towards "real".
- **Not a problem**: counts against.
- **Expected change**: the change was real but planned (a deploy, a scaling change). It counts
  neither way.

Answering again changes your answer. Answers are kept per service and per kind of finding, so one
noisy service doesn't change the numbers for another.

Answers are stored in Ops Signals' own database (the PostgreSQL that holds findings and cases),
in `ops_finding_feedback`: one row per finding with its service, metric, kind of finding and
answer. There is one answer per finding, the team's: the latest replaces the one before. When it was
given in the Grafana plugin connected through Grafana, the row also keeps who gave it, and the card
says so ("Answered Expected change by priya · 10m ago"). An answer from elsewhere clears the name
rather than keep someone else's.

## Your answers move findings between the lists

Once a kind of finding on a service has **5 or more answers**, those answers decide its list on
that service, ahead of the tests:

| Your team's answers | What happens | Shown as |
| --- | --- | --- |
| A Context only kind (spikes, patterns) was real **at least half** the time | It moves up to Needs attention on that service | **Confirmed by your team**, with "Moved to Needs attention: your team said 4 of 6 ... were real" |
| A Needs attention kind was real **less than 1 in 5** times | It moves down to Context only on that service | **Usually not a problem here**, with "Moved to Context only: ..." |

- It applies to every finding of that kind on that service, including new ones nobody answered yet.
- Other services keep the tested lists until their own teams answer.
- **Data problems never move down**: a metric that stopped reporting is a fact, whatever the answers.
- Changing answers can move a kind of finding back.
- Fewer than 5 answers never move anything, however one-sided.

The answers don't change the analyzers or the router; they only decide what asks for attention on
your service.

## Where the tested numbers come from

They come from the finding-trust benchmark (`benchmark/finding_trust/`), which replays recorded
metrics through the same analysis path a scheduled run uses and checks each finding against
problems marked by outside researchers:

- **RCAEval RE1** (Pham et al., 2024, CC BY 4.0): 375 faults (CPU, memory, disk, network delay,
  packet loss) injected at known moments into three microservice demo shops. This is the main
  source.
- **NAB cloud-server metrics** (Numenta Anomaly Benchmark, 17 series): kept alongside for
  comparison. It gave too few level changes to show a number of its own.

Every rate is compared with what an alert raised at a random moment would score on the same data,
because a finding can look accurate simply because problems were happening most of the time. A
group is only shown with a number when at least 30 findings like it were checked.

The numbers live in `config/finding_trust.yaml`, generated from a recorded run. To refresh them:

```bash
.venv/bin/python -m benchmark.finding_trust.run --nab-category realAWSCloudwatch \
    --rcaeval-systems RE1-OB,RE1-SS,RE1-TT --rcaeval-repeats all
.venv/bin/python -m benchmark.finding_trust.export benchmark/results/<run>/results.json
```

The run writes a local report (`report.html`) next to its results, with every group, how it
compares with a random alert, and the limits below.

## How a finding gets its group

The backend (`backend/app/services/finding_trust.py`) looks at the kinds of checks behind a
finding, not the number of analyzers:

| Group | When | List |
| --- | --- | --- |
| `data_problem` | a data gap or flatline signal, or the Data Quality category | Needs attention |
| `level_change_agree` | a change-point check (ruptures or baseline_shift, which share one detector) plus a different check | Needs attention |
| `level_change_single` | a change-point check alone | Needs attention |
| `spike` | unusual values without a level change | Context only |
| `pattern` | trends, forecasts, repeating patterns | Context only |

A finding whose signals weren't stored falls back to its category.

## What the numbers don't promise

- **98% real still means about 1 in 50 isn't.** Take a quick look before you act, especially
  before you page someone.
- **Test data isn't your system.** Your team's answers replace the tested number for your service.
- **Tested with the default settings.** A finding made with per-service analyzer settings
  ([configuration](configuration.md#per-service-analyzer-settings)) shows "Custom settings · not
  tested" instead of a tested rate; your team's answers still count.
- **No early warnings yet.** A finding says something has changed, not that something will break.
  Forecasts stay in "Context only" until they're tested against problems that built up slowly.
- **Missing a problem is possible.** In the tests, slow-network faults were caught less often than
  CPU and memory faults.
- **Importance isn't trust.** In the tests, the importance score didn't reliably separate real
  problems from noise, so it no longer decides the badge.

## API

- `GET /api/findings` and `GET /api/findings/{id}` return a `trust` object on each finding:
  `group`, `tier` (`needs_attention` or `context`), `badge`, `checks`, `tested` (or null),
  `service` (`real`, `answered`, `min_answers`, `scope`: `service`, or `metric` when the finding
  has no service label), `your_answer`, and `moved` (`up`, `down` or null,
  when your answers moved it to the other list; the badge is then `team_confirmed` or null).
  A finding made with per-service settings has `tested: null` and `custom_settings: true` in
  `trust`, and a `custom_settings` object (`settings`, `overrides`) on the finding itself.
- `POST /api/findings/{id}/feedback` with `{"verdict": "real_problem" | "expected_change" |
  "not_a_problem"}` stores the answer and returns the finding with its trust recomputed.

Answers are stored in `ops_finding_feedback` (created at startup; see
`backend/migrations/009_finding_feedback.sql`).
