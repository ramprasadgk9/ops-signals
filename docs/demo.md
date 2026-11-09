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

Requirements: Docker with Compose v2.20 or later and about 4 GB of memory for Docker (8 GB with
`--profile ai`, see [Turn on AI](#turn-on-ai)). The demo downloads the published images of the
latest release; if they can't be downloaded, Compose builds them from this checkout instead (10+
minutes the first time, mostly PyTorch for the embedding model). Compose keeps the images it
downloaded, so to move to a newer release run `docker compose -f docker-compose.demo.yml pull`
first. On a checkout that is ahead of the latest release, such as `main` between releases, add
`--build` so the images match the code (see "Build the images yourself" under [Common tasks](#common-tasks)).

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

The same steps are in the app: a **Things to try** guide in the corner, on by default, with a
button for each step that takes you there and ticks itself off. Progress is kept in your browser.
`OPS_SIGNALS_DEMO_TOUR=false` in front of the command hides it. There are ten steps with AI off and
eleven with AI on ([Turn on AI](#turn-on-ai)):

- With AI on, **Let it investigate checkout's slowdown** comes after the pods step. It opens
  today's checkout-api finding; click **Investigate**, and the step ticks off when the
  investigation starts. With AI off it isn't in the guide, since Investigate needs AI.
- With AI off, the case step is **Make a case** and ticks off when the case opens; with AI on, it's
  **Make a case and draft a root cause** and ticks off with **Draft from case**.
- **Analyze a metric yourself** opens New Analysis. Under **CSV Upload**, **Analyze it** on a
  sample file analyzes it in a click, and **Download CSV** gives you the file, to see what your own
  CSV should look like.

1. **Read the alert as it reached the team** at http://localhost:8090: what happened, the deploy
   (`v2.14.0`), and the past case with its fix (roll back).
2. **Overview**: what needs attention now, and the **Shift handoff** button.
3. **Findings → checkout-api**: the pods chip (**3 new pods** or **3 of 6 pods**) says where the
   change came from: hover for the three pods the rollout started. And **Seen before** opens the past case and its fix. With AI on,
   click **Investigate** ([how it works](investigate.md)): it checks the `v2.14.0` deploy, the
   pods and the past case, and lists where to look; you confirm the cause. Then **Create Case**;
   with AI on, try **Draft from case** on Root Cause.
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
Nothing is sent anywhere unless you choose a provider. Three ways:

**A model in its own container** (the simplest). The demo's `ai` profile adds an Ollama container,
downloads `gemma3:4b` into it, and switches AI on:

```bash
docker compose -f docker-compose.demo.yml --profile ai up
```

- First start: about 10 GB to download (the Ollama image is about 7 GB, the model about 3 GB),
  kept in Docker for next time. Give Docker about 8 GB of memory.
- It runs on CPU, so each answer takes 5-20 seconds. Combined pattern explanations are written in
  the background and show the next time you open the page.
- Another model: add `DEMO_AI_MODEL=<name>` in front of the command.
- Stop it with `docker compose -f docker-compose.demo.yml --profile ai down -v`. The downloaded
  model is in the `ollama_models` volume; `down -v` removes it too.

**A model API you already have** (nothing to download). Any server that speaks the OpenAI chat
completions API: a hosted API, a gateway, or a model server on your machine. Copy the template,
fill in three lines, and start the demo with it:

```bash
cp demo/ai-api.env.example demo/ai-api.env
docker compose -f docker-compose.demo.yml --env-file demo/ai-api.env up
```

| Setting | What to put |
|---|---|
| `DEMO_AI_URL` | The API root, ending before `/chat/completions`, e.g. `https://api.example.com/v1`. For a server on your machine use `host.docker.internal` instead of `localhost`. |
| `DEMO_AI_KEY` | The API key, sent as `Authorization: Bearer <key>`. Leave empty if the server needs none. |
| `DEMO_AI_MODEL` | The model name the server expects. Required: without it AI stays off and the backend log says why. |

- `demo/ai-api.env` is gitignored. Keeping the key there keeps it out of your shell history; you
  can also put the three settings in front of the command instead.
- The backend log shows `AI is on: <model> from <url>` at start; the key is never printed.
- When you use an AI feature, the case and finding text it needs is sent to that API.
- Set together with `--profile ai`, the API wins and the downloaded model isn't used.
- **The Anthropic API** has its own provider: in the same file, uncomment the `OPS_SIGNALS_*` block
  instead and set the key and a model name (e.g. `claude-haiku-5-5`). Leave the `DEMO_AI_*` lines
  empty.
- **Things to try** is on by default in every way of starting the demo. `OPS_SIGNALS_DEMO_TOUR=false`
  hides it.

**A model server you already run, with your own settings.** Pass the settings when you start the demo. For
[Ollama](https://ollama.com) on your own machine, with a model already pulled:

```bash
OPS_SIGNALS_AI_ENABLED=true OPS_SIGNALS_AI_PROVIDER=ollama OPS_SIGNALS_OLLAMA_URL=http://host.docker.internal:11434 OPS_SIGNALS_OLLAMA_MODEL=gemma3:4b docker compose -f docker-compose.demo.yml up -d
```

Any OpenAI-compatible endpoint works too (`OPS_SIGNALS_AI_PROVIDER=openai_compatible` with
`OPS_SIGNALS_OPENAI_BASE_URL`, `OPS_SIGNALS_OPENAI_MODEL` and, if it needs one,
`OPS_SIGNALS_OPENAI_API_KEY`); [ai-features.md](ai-features.md) lists the providers and every place
AI is used. Settings you pass win over the `ai` profile, except an Ollama with no address (see below).

For **Investigate** with a model on your machine, give it more time:
`OPS_SIGNALS_OLLAMA_TIMEOUT_SECONDS=300 OPS_SIGNALS_INVESTIGATION_ROUND_SECONDS=300` in front of the
command ([settings for a local model](investigate.md#settings-for-a-local-model)).

### Which AI does the demo use?

The backend log says it in one line at start, for example
`AI is on: qwen3:14b from Ollama on your machine (http://host.docker.internal:11434)`. It picks, in
this order:

1. **A model API** (`DEMO_AI_URL` and `DEMO_AI_MODEL`), whatever else is set.
2. **The `ai` profile's model**, when it runs and you haven't chosen another AI.
3. **Your own settings**, from the command or from the repo's `.env`: Docker Compose reads `.env`
   by itself, so the dev stack's AI settings reach the demo too. An Ollama address that is empty or
   `localhost` would point at the backend's own container, so the demo uses the `ai` profile's
   model when it runs, and otherwise Ollama on your machine (`host.docker.internal:11434`, with
   3 minutes a reply and 5 minutes an Investigate round unless you set them).

`--env-file demo/ai-api.env` reads that file instead of `.env`.

Either way, **Integrations → AI provider → Test connection** checks it. Every AI line is checked
before it's shown: a sentence naming a number, version or fix that isn't in the case is dropped, so
a draft can come back shorter, or as "not available", rather than wrong.

## Host it as a public demo

To put the demo on a server and share a link, turn on **demo mode**. It's for a site strangers
visit, so it changes a few things (off by default, and the local demo above stays as it is):

- **A banner** on every page: sample data, nothing real, and when the site resets.
- **Things to try**: the guide from the local demo, always on in demo mode; each visitor's progress
  starts over when the site resets.
- **Recorded AI answers**: AI buttons show answers a real model gave when the demo was built,
  labeled **Recorded example**. No model runs on the server.
- **View-only settings**: anything that would change the site for everyone, reach in from outside,
  or keep someone's own data is refused, with the reason on screen. Visitors can still open and work
  cases, answer "Was this real?", ask Ops Signals, and analyze the demo's metrics or a sample file in
  New Analysis (and download the sample to see what a CSV should look like).

```bash
OPS_SIGNALS_DEMO_MODE=true OPS_SIGNALS_DEMO_RESET_HOURS=2 OPS_SIGNALS_AI_ENABLED=true OPS_SIGNALS_AI_PROVIDER=recorded docker compose -f docker-compose.demo.yml up -d
```

| Setting | What it does |
|---|---|
| `OPS_SIGNALS_DEMO_MODE=true` | Turns demo mode on |
| `OPS_SIGNALS_DEMO_RESET_HOURS` | How often you reset the site; the banner counts down to it. Resetting is up to you (for example `down -v` and `up -d` on a timer). Keep it at 2 or less: search-svc's cascading-failure pattern lasts about 2 hours |
| `OPS_SIGNALS_AI_PROVIDER=recorded` | Replays `config/demo_ai/recorded_answers.json` (another file: `OPS_SIGNALS_AI_RECORDED_FILE`) |
| `OPS_SIGNALS_DEMO_RUN_YOURSELF_URL` | Where "Run it yourself" goes (default: the README's one-command install) |

What's refused, and how it tells a visitor from the demo itself: a request that came through the
web UI's proxy (it carries `X-Forwarded-For`) is checked; the demo's own services (the seeder,
Alertmanager, the OTLP sender) call the backend directly. The list is in `backend/app/demo.py`.
Expose only the web UI port (8080) to the internet, not Prometheus, Alertmanager or the Slack sink.

**How recorded answers are matched.** Each reset seeds the story again, so times, case numbers and
durations change. An answer is replayed for the same question with its numbers ignored, but not if
it quotes a number from the day it was recorded that today's data doesn't have (a percentage, a case
number): the feature then shows its usual text without AI. A visitor's own free-form question to
Ask Ops Signals gets the answer from docs and cases, without AI.

### Record the AI answers

Re-record after the story or an AI feature's prompt changes. With a model in its own container:

```bash
mkdir -p tmp/recordings
OPS_SIGNALS_AI_RECORD_TO=/recordings/recorded_answers.json docker compose -f docker-compose.demo.yml -f tmp/recordings.yml --profile ai up -d --build
./scripts/record_demo_ai.py --web-url http://localhost:8080
cp tmp/recordings/recorded_answers.json config/demo_ai/recorded_answers.json
```

`tmp/recordings.yml` mounts the folder the answers are written to:

```yaml
services:
  backend:
    volumes:
      - ./tmp/recordings:/recordings
```

The script asks for every AI answer a visitor can get on the story and prints which ones the model
gave; some can come back "not available" when a feature's checks drop the model's sentences.

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
