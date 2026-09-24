# Five-Minute Demo

One command starts Ops Signals with an incident already in progress: a deploy, a latency shift, a
Prometheus alert, and a similar incident from three weeks ago. You don't need Python, Node,
a Slack workspace, or any data of your own.

```bash
git clone https://github.com/ramprasadgk9/operational-intelligence.git
cd operational-intelligence
docker compose -f docker-compose.demo.yml up
```

Within about a minute of the containers starting, open:

| URL | What's there |
|---|---|
| http://localhost:8090 | **The enriched alert**, rendered the way it would appear in Slack |
| http://localhost:8080 | **Ops Signals**: the finding (Findings), the past incident (Cases), change history |
| http://localhost:9091 | Prometheus, with the latency series and the firing alert |
| http://localhost:9094 | Alertmanager |

Requirements: Docker with Compose v2 and about 4 GB of memory for Docker. First start pulls the
images (a few GB, mostly PyTorch for the embedding model). If the published images aren't
available, Compose builds them from source instead, which takes 10+ minutes the first time.

## The story

`checkout-api` has served p95 latency around 180ms all day. Then:

1. **Deploy `v2.14.0`** lands, 48 minutes before you ran `up`.
2. **Three minutes later**, p95 latency steps up to about 320ms and stays there.
3. **The `CheckoutApiLatencyHigh` alert fires** (a plain Prometheus threshold rule) and
   Alertmanager routes it to Ops Signals.
4. **Ops Signals enriches the alert** and posts one message:
   - **📈 What happened:** it pulls the last 6h of the series from Prometheus, runs the analyzers,
     and reports the shift and when it started.
   - **🚀 What changed:** the shift started 3 minutes after deploy `v2.14.0`.
   - **🧠 Seen before:** three weeks ago, deploy `v2.9.0` caused the same kind of shift on the same
     service. That case was resolved by rolling back, and Ops Signals links to it.

Nothing in that message is scripted. The seeder only records the deploys and the past incident
through the public API. The alert travels the real path (Prometheus → Alertmanager →
`/api/integrations/alertmanager`), and the analysis, deploy correlation and similar-case search are
the same code that runs against your own Prometheus.

## What runs

| Service | Role |
|---|---|
| `postgres`, `qdrant` | Storage: findings, cases, change events; operational memory |
| `backend`, `web` | Ops Signals API and UI (the UI proxies `/api` to the backend) |
| `demo-history` | One-shot: picks the incident timeline and writes 7h of metric history |
| `prometheus-backfill` | One-shot: loads that history into Prometheus with `promtool`, so there's a baseline from the first minute |
| `demo-metrics` | Live scrape target that continues the series |
| `prometheus` | Scrapes `demo-metrics` and evaluates the alert rule |
| `demo-seeder` | One-shot: records deploys, then creates, resolves and indexes the past incident through the API |
| `alertmanager` | Routes the alert to Ops Signals. Starts only after the seeder finishes |
| `slack-sink` | Accepts Slack webhook posts and shows them as a Slack-style channel |

The scenario itself (service, metric, shift size, timings, versions) lives in
[`demo/scenario.py`](../demo/scenario.py). The history backfill, the live target and the seeder
all read it from there.

## Common tasks

**Start over with a fresh incident.** The timeline is fixed on first start, so running `up` again
later keeps the same incident, and after about 6h it has scrolled out of the analysis window.
Reset everything:

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

`scripts/demo_smoke_test.py` waits for the enriched alert and checks each part of it: the shift
was found, the deploy was correlated, and the past case and its fix were matched. CI runs the same
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
| `port is already allocated` | 8080, 8090, 9091 or 9094 is in use | Set `DEMO_WEB_PORT` / `DEMO_SLACK_PORT` / `DEMO_PROMETHEUS_PORT` / `DEMO_ALERTMANAGER_PORT` |
| `error from registry: denied`, then a long build | The published images aren't available, so Compose is building them | Wait for the build, or check the images are public on GHCR |
