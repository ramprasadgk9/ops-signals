# Five-Minute Demo

One command starts Ops Signals with four services of an online shop that each have something going
on: a deploy that broke latency, a database problem that came back after a fix, a release nobody
announced, and an OTLP service whose case is being worked on. You don't need Python, Node, a Slack
workspace, or any data of your own.

```bash
git clone https://github.com/ramprasadgk9/ops-signals.git
cd ops-signals
docker compose -f docker-compose.demo.yml up
```

Within a few minutes of the containers starting, open:

| URL | What's there |
|---|---|
| http://localhost:8090 | **The enriched alert**, rendered the way it would appear in Slack |
| http://localhost:8080 | **Ops Signals**: Overview, Findings, Cases, Recurring Problems, Behavior Intelligence |
| http://localhost:9091 | Prometheus, with the demo series and the firing alert |
| http://localhost:9094 | Alertmanager |

Requirements: Docker with Compose v2 and about 4 GB of memory for Docker. First start pulls the
images (a few GB, mostly PyTorch for the embedding model). If the published images aren't
available, Compose builds them from source instead, which takes 10+ minutes the first time.

## The story

| Service | Data | What happens | What it shows |
|---|---|---|---|
| `checkout-api` | Prometheus | CI deploy `v2.14.0`, then p95 latency steps from about 180ms to 320ms; the `CheckoutApiLatencyHigh` alert fires | The enriched Slack alert, the deploy behind it, and a case from five weeks ago fixed by a rollback, published with a write-up |
| `payments-db` | Prometheus | Connection wait and active connections climb together | The **Database connection pool exhaustion** pattern; **fix didn't stick** (the pool ran out 9 days ago and was fixed by raising its size, with the leak left open); **Recurring Problems** (the third time in 40 days) |
| `search-svc` | Prometheus | Version `1.9.0` shows up on `search_build_info` with no CI event, then latency and errors jump together and the index merge backlog grows | A **deploy found automatically**; the **Possible cascading failure** pattern; a metric the wording file doesn't describe; "Was this real?" answers on past findings, counting toward 5 |
| `orders` | OTLP | Failed orders climb after CI deploy `v3.2.0`; order processing slows for 3 minutes | **OTLP** next to Prometheus; a case **in progress**; a finding made with the orders team's own analyzer settings (**Custom settings** tag) |

Times are relative to when you ran `up`: the checkout deploy lands 48 minutes before, payments-db
starts climbing an hour before, the search-svc release lands 35 minutes before, and the orders
deploy 94 minutes before. Metric history is backfilled, so the analyzers have a baseline from the
first minute.

What's real and what's seeded:

- **Live**: today's problems. Prometheus scrapes a demo target and orders sends OTLP; a scheduled
  analysis runs every 5 minutes; deploy discovery reads `search_build_info`; the alert goes
  Prometheus → Alertmanager → `/api/integrations/alertmanager` → Slack sink. Findings, patterns,
  "Seen before", "came back" and the alert text are produced by the same code that runs against
  your own data.
- **Seeded** through the public API, then dated back: the history. The CI deploy events, the four
  past cases (analyzed from CSVs of the same shapes, with their root causes and fixes), the
  checkout write-up, the "Was this real?" answers, and the orders case notes.

AI features need a provider (see [ai-features.md](ai-features.md)). Without one, they show their
usual fallback, and everything else works.

## Things to try

1. **Read the alert as it reached the team** at http://localhost:8090: what happened, the deploy
   (`v2.14.0`), and the past case with its fix (roll back).
2. **Overview**: what needs attention now, and the **Shift handoff** button.
3. **Findings → checkout-api**: the **Seen before** chip opens the past case and its fix. Then
   **Create Case** and try the root cause and resolution drafts.
4. **Findings → payments-db**: the warning that the problem came back 9 days after a fix, with
   what was left open. The old case shows the same banner.
5. **Recurring Problems**: payments-db's three cases, their causes and fixes, and the next step.
6. **Findings → Combined patterns** (or **Behavior Intelligence**): pool exhaustion on payments-db
   and cascading failure on search-svc, each with the single-metric findings it was made from.
7. **Findings → search-svc**: "started after deploy `1.9.0`", tagged **Found automatically**.
8. **Answer "Was this real?"** on a search-svc finding and watch its count move toward 5.
9. **Cases → In progress**: the orders case. On **Findings → orders**, the processing finding
   carries **Custom settings**; its details show the team's setting and reason.
10. **Assistant**: ask "Have we seen payments-db connection pool problems before?". It lists the
    past cases and findings it found; with an AI provider it also writes the answer from them.

## What runs

| Service | Role |
|---|---|
| `postgres`, `qdrant` | Storage: findings, cases, change events; operational memory |
| `backend`, `web` | Ops Signals API and UI (the UI proxies `/api` to the backend) |
| `demo-history` | One-shot: picks the timeline and writes 7h of metric history |
| `prometheus-backfill` | One-shot: loads that history into Prometheus with `promtool`, so there's a baseline from the first minute |
| `demo-metrics` | Live scrape target that continues the Prometheus series |
| `prometheus` | Scrapes `demo-metrics` and evaluates the alert rule |
| `demo-otlp` | Sends the orders metrics over OTLP, as an OpenTelemetry Collector would: 6.5h of history, then a point every 30s |
| `demo-seeder` | One-shot: records the history above, starts the scheduled analysis, and opens the orders case |
| `alertmanager` | Routes the alert to Ops Signals. Starts only after the seeder finishes |
| `slack-sink` | Accepts Slack webhook posts and shows them as a Slack-style channel |

The story itself (services, metrics, shapes, timings, versions, past cases) lives in
[`demo/scenario.py`](../demo/scenario.py). The orders team's settings file is
[`demo/config/analyzer-overrides/orders-team.yml`](../demo/config/analyzer-overrides/orders-team.yml).

## Common tasks

**Start over with a fresh story.** The timeline is fixed on first start, so running `up` again
later keeps the same one, and after about 6h it has scrolled out of the analysis window. Each
5-minute analysis also adds the ongoing problems again, so the lists grow the longer it runs. Reset
everything:

```bash
docker compose -f docker-compose.demo.yml down -v
docker compose -f docker-compose.demo.yml up
```

**Post to a real Slack channel.** Create an incoming webhook (see
[alert-enrichment.md](alert-enrichment.md)) and pass it in. The Slack sink then stays empty:

```bash
DEMO_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/... docker compose -f docker-compose.demo.yml up
```

**Change ports.** Set `DEMO_WEB_PORT`, `DEMO_SLACK_PORT`, `DEMO_PROMETHEUS_PORT` or `DEMO_ALERTMANAGER_PORT`. The demo runs as
its own Compose project (`ops-signals-demo`) and doesn't publish Postgres or Qdrant, so it can run
next to the development stack from `scripts/run_all.sh`, as long as those four ports are free.

**Build the images yourself** instead of pulling them:

```bash
docker compose -f docker-compose.demo.yml up --build
```

## Checking the demo and re-recording the GIF

`scripts/demo_smoke_test.py` waits for the enriched alert and checks each part of it (the shift
was found, the deploy was correlated, the past case and its fix were matched), then checks the rest
of the story through the API: both patterns, the fix that didn't stick, the recurring problem, the
found deploy, the OTLP finding and case, the custom settings, and the write-up. CI runs the same
check on every change that could affect the demo (`.github/workflows/demo-smoke.yml`).

```bash
docker compose -f docker-compose.demo.yml up -d
./scripts/demo_smoke_test.py
```

The README GIF is recorded from a running demo, so re-record it when the UI or the message changes.
This writes `docs/screenshots/images/demo/ops-signals-demo.gif`:

```bash
./scripts/record_demo_gif.sh
```

It drives the frontend's Playwright Chromium (`cd frontend && npx playwright install chromium`)
through the same screens each time, then assembles the frames with Pillow from the project virtualenv.

The screenshot gallery ([`screenshots.md`](screenshots.md)) is recorded from the demo the same way,
with `./scripts/record_screenshots.sh`.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| The Slack sink stays empty | Seeding or enrichment hasn't finished, or failed | `docker compose -f docker-compose.demo.yml logs demo-seeder backend` |
| `demo-seeder` exits with `backend not ready` | The backend couldn't reach Qdrant or load the embedding model | `docker compose -f docker-compose.demo.yml logs backend` |
| The message says *No significant change detected* | The incident has aged out of the 6h analysis window | Reset with `down -v` (above) |
| No orders case | The OTLP history hadn't been analyzed within 7 minutes, so the seeder skipped it | `docker compose -f docker-compose.demo.yml logs demo-otlp backend` |
| `port is already allocated` | 8080, 8090, 9091 or 9094 is in use | Set `DEMO_WEB_PORT` / `DEMO_SLACK_PORT` / `DEMO_PROMETHEUS_PORT` / `DEMO_ALERTMANAGER_PORT` |
| `error from registry: denied`, then a long build | The published images aren't available, so Compose is building them | Wait for the build, or check the images are public on GHCR |
