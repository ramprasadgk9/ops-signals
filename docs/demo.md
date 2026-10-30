# Five-Minute Demo

One command starts Ops Signals with four services of an online shop that each have something going
on: a deploy that broke latency, a database problem that came back after a fix, a release nobody
announced, and an OTLP service whose case is being worked on. You don't need Python, Node, a Slack
workspace, or any data of your own.

```bash
git clone https://github.com/ramprasadgk9/ops-signals.git
cd ops-signals
docker compose -f docker-compose.demo.yml up --build
```

Within a few minutes of the containers starting, open:

| URL | What's there |
|---|---|
| http://localhost:8090 | **The enriched alert**, rendered the way it would appear in Slack |
| http://localhost:8080 | **Ops Signals**: Overview, Findings, Cases, Recurring Problems, Behavior Intelligence |
| http://localhost:9091 | Prometheus, with the demo series and the firing alert |
| http://localhost:9094 | Alertmanager |

Requirements: Docker with Compose v2.20 or later and about 4 GB of memory for Docker (8 GB with
`--profile ai`, see [Turn on AI](#turn-on-ai)). `--build` builds the images from this checkout,
which takes 10+ minutes the first time (mostly PyTorch for the embedding model); without it,
Compose uses the published images, which can be older than the code.

## The story

| Service | Data | What happens | What it shows |
|---|---|---|---|
| `checkout-api` | Prometheus | CI deploy `v2.14.0` replaces its 3 pods, then p95 latency steps from about 180ms to 320ms; the `CheckoutApiLatencyHigh` alert fires | The enriched Slack alert, the deploy behind it, **which pods** (the 3 new ones from the rollout), and a case from five weeks ago fixed by a rollback, published with a write-up |
| `payments-db` | Prometheus | Connection wait and active connections climb together | The **Database connection pool exhaustion** pattern; **fix didn't stick** (the pool ran out 9 days ago and was fixed by raising its size, with the leak left open); **Recurring Problems** (the third time in 40 days) |
| `search-svc` | Prometheus | Version `1.9.0` shows up on `search_build_info` with no CI event, then latency and errors jump together on one of its 4 pods, and the index merge backlog grows | A **deploy found automatically**; the **Possible cascading failure** pattern; **1 of 4 pods**; a metric the wording file doesn't describe; "Was this real?" answers on past findings, counting toward 5 |
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

AI features are off unless you give the demo a provider ([Turn on AI](#turn-on-ai)). Without one,
they show their usual fallback, and everything else works.

## Things to try

1. **Read the alert as it reached the team** at http://localhost:8090: what happened, the deploy
   (`v2.14.0`), and the past case with its fix (roll back).
2. **Overview**: what needs attention now, and the **Shift handoff** button.
3. **Findings → checkout-api**: the pods chip (**3 new pods** or **3 of 6 pods**) says where the
   change came from: hover for the three pods the rollout started. And **Seen before** opens the past case and its fix. Then **Create Case**; with AI
   on, try **Draft from case** on Root Cause.
4. **Findings → payments-db**: the warning that the problem came back 9 days after a fix, with
   what was left open; with AI on, **Why might it not have held?**. The old case shows the same
   banner.
5. **Recurring Problems**: payments-db's three cases, their causes and fixes, and the next step.
   With AI on, **Draft a runbook** (Finding details → Seen before?) turns those fixes into steps.
6. **Findings → Combined patterns** (or **Behavior Intelligence**): pool exhaustion on payments-db
   and cascading failure on search-svc, each with the single-metric findings it was made from.
7. **Findings → search-svc**: "started after deploy `1.9.0`", tagged **Found automatically**, and
   the **1 of 4 pods** chip: only `search-svc-2` went bad.
8. **Answer "Was this real?"** on a search-svc finding and watch its count move toward 5.
9. **Cases → In progress**: the orders case, with notes and a rollback on the canary pods. With AI
   on, draft its Root Cause and Resolution. On **Findings → orders**, the processing finding carries
   **Custom settings**; its details show the team's setting and reason.
10. **Assistant**: ask "Have we seen payments-db connection pool problems before?". It lists the
    past cases and findings it found; with an AI provider it also writes the answer from them.

## Turn on AI

The demo's AI is off unless you turn it on. The demo's `ai` profile downloads `gemma3:4b` (the dev
stack's own `ai` profile in `docker-compose.yml` pulls `qwen2.5:3b` instead, see the README).
Nothing is sent anywhere unless you choose a provider. Two ways:

**A model in its own container** (the simplest). The demo's `ai` profile adds an Ollama container,
downloads `gemma3:4b` into it, and switches AI on:

```bash
docker compose -f docker-compose.demo.yml --profile ai up --build
```

- First start: about 10 GB to download (the Ollama image is about 7 GB, the model about 3 GB),
  kept in Docker for next time. Give Docker about 8 GB of memory.
- It runs on CPU, so each answer takes 5-20 seconds. Combined pattern explanations are written in
  the background and show the next time you open the page.
- Another model: add `DEMO_AI_MODEL=<name>` in front of the command.
- Stop it with `docker compose -f docker-compose.demo.yml --profile ai down -v`. The downloaded
  model is in the `ollama_models` volume; `down -v` removes it too.

**A model server you already run, or an API.** Pass the settings when you start the demo. For
[Ollama](https://ollama.com) on your own machine, with a model already pulled:

```bash
OPS_SIGNALS_AI_ENABLED=true OPS_SIGNALS_AI_PROVIDER=ollama OPS_SIGNALS_OLLAMA_URL=http://host.docker.internal:11434 OPS_SIGNALS_OLLAMA_MODEL=gemma3:4b docker compose -f docker-compose.demo.yml up -d --build
```

Any OpenAI-compatible endpoint works too (`OPS_SIGNALS_AI_PROVIDER=openai_compatible` with
`OPS_SIGNALS_OPENAI_BASE_URL`, `OPS_SIGNALS_OPENAI_MODEL` and, if it needs one,
`OPS_SIGNALS_OPENAI_API_KEY`); [ai-features.md](ai-features.md) lists the providers and every place
AI is used. Settings you pass win over the `ai` profile.

Either way, **Integrations → AI provider → Test connection** checks it. Every AI line is checked
before it's shown: a sentence naming a number, version or fix that isn't in the case is dropped, so
a draft can come back shorter, or as "not available", rather than wrong.

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
later keeps the same one. It ages: search-svc's cascading-failure pattern stops matching after
about 2 hours (its bursts become normal for the 6h window), and after about 6h today's problems
have scrolled out of the analysis window. Each 5-minute analysis also adds the ongoing problems
again, so the lists grow the longer it runs. Reset everything:

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
