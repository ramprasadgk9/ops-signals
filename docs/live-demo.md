# Live Demo

`scripts/demo_live.py` drives a live demo on the local stack. In front of an audience, you pick a
scenario from a menu. A few seconds later a real alert goes through Alertmanager, Ops Signals
analyzes the series, and the enriched message shows which pods the change came from and how it
lines up with deploys.

It uses the same path as production: Prometheus scrapes the metrics, Alertmanager routes the alert
to `/api/integrations/alertmanager`, the backend runs the analyzers and the pod drill-down, and the
message is posted to a Slack webhook. The only thing made up is the data. The script serves
per-pod metrics and changes them on demand.

For a demo with no setup at all, use [`docs/demo.md`](demo.md) (one `docker compose` command, one
pre-built incident). Use this one when you want to show several scenarios live.

## Setup (once)

Add to `.env`:

```bash
OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED=true
OPS_SIGNALS_DRILLDOWN_ENABLED=true
OPS_SIGNALS_ALERT_SLACK_WEBHOOK_URL=http://localhost:8095/webhook
OPS_SIGNALS_ALERT_MIN_STEP=5s
OPS_SIGNALS_ALERT_SCRAPE_INTERVAL=5s
```

- The webhook points at the Slack lookalike the script serves. Use a real Slack webhook instead to
  post to a channel; the terminal summary then won't show the message, but Slack will.
- The 5s step lets the analysis work on minutes of history instead of hours. The script's metrics
  are scraped every 5s (the `ops-signals-live-demo` job in
  `grafana/prometheus/prometheus.alerting.yml`). Leave these two settings out outside a demo.

## Run it

Terminal 1:

```bash
./scripts/run_all.sh
```

Terminal 2, once the backend is up:

```bash
./scripts/demo_live.py
```

Open **http://localhost:8095** next to the terminal. The first alert needs about 4 minutes of
metric history. The menu shows a countdown, and you can pick a scenario before then (it waits).
Each scenario takes about 2 minutes: 90 seconds for the change to show in the metrics, then
Alertmanager's 10-second group wait and the analysis.

## Scenarios

| # | What happens | What the message shows |
|---|---|---|
| 1 | **Rollout.** Deploy `v2.4.x` to `checkout`; a minute later two new pods come up at ~600 ms while the four old ones stay at ~180 ms | 📈 a step change. 📍 *2 of 6 pods rose: checkout-5, checkout-6*, both new, "looks like a rollout in progress". 🚀 *Started 1 min after deploy v2.4.x* |
| 2 | **Slow rise.** `orders-worker` consumer lag has been rising since the script started; deploy `v5.1.x` lands 2 minutes before the alert | 📈 a gradual trend. 🚀 *Gradual upward trend with no clear start time*, with the deploy listed for reference and no "started after" claim |
| 3 | **Spike on a slow rise.** Deploy `v3.2.x` to `payments-worker`; a minute later one pod spikes for 30 seconds | 📈 unusual activity. 📍 *Only pod payments-worker-3 rose*. 🚀 *Spike started 1 min after deploy v3.2.x*, noting the slow rise it sits on |
| 4 | **Staging deploy ignored.** `cart` slows on every pod after prod deploy `v6.9.x`; a staging deploy `v7.0.x-rc1` lands in between | 📍 *All 4 pods rose*: not one bad pod. 🚀 only `v6.9.x`; the staging deploy is skipped because the alert is `env=prod` |

The terminal prints the "What happened" and "What changed" sections of each message as it
arrives. `r` resolves the alerts fired so far (a ✅ follow-up arrives within a minute). Each
scenario runs once per start of the script, because the pods it changes stay changed. Restart the
script to run them again: each run uses its own series (a `demo_run` label) and its own deploy
versions (the `x` in `v2.4.x`), so it never mixes with the last run.

The same results appear in the web UI (http://localhost:5174). On **Alerts** (and the
Overview's alerts panel), each alert row shows a **Where** and **What changed** box, and the
timeline lane marks each deploy with ▼ (hover for the version). **Findings** shows the finding with
the same pod breakdown.

## Troubleshooting

| What you see | Fix |
|---|---|
| `Prometheus has no 'ops-signals-live-demo' scrape job` | Prometheus started before the job existed. Run `docker compose -f docker-compose.yml -f docker-compose.alerting.yml up -d --force-recreate prometheus` |
| `Alertmanager not reachable` | Set `OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED=true` in `.env` and restart `run_all.sh` |
| `Port 9105 ... is in use` / `Port 8095 ...` | Another copy of the script is running, or something else uses the port |
| `No message after 6 min` | Check `.tmp_ops_signals_api.log`, and that the Slack webhook in `.env` is `http://localhost:8095/webhook` |
| Message says *Not analyzed: not enough data* | `OPS_SIGNALS_ALERT_MIN_STEP=5s` and `OPS_SIGNALS_ALERT_SCRAPE_INTERVAL=5s` aren't set, so the analysis uses a 30s step and 4 minutes is too little history |
| No 📍 *Where* line | `OPS_SIGNALS_DRILLDOWN_ENABLED=true` isn't set |
| Older deploys listed too, e.g. `v2.4.37` under `v2.4.38` | You restarted the script within 30 minutes. The last run's deploys are real events in the change window, so they're listed; each run has its own version numbers so they're easy to tell apart |
