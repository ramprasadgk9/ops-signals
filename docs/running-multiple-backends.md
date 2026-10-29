# Running more than one backend

You can run several Ops Signals backends against the same PostgreSQL database. Common reasons:

- the web UI backend and the Grafana plugin backend share one database;
- a second backend so the API stays up while one is restarted or upgraded.

A second backend does **not** make analysis faster. Each scheduled analysis runs on one backend,
and OTLP analysis runs on one backend at a time (see below). Add a backend for availability, not
for capacity. In a load test with one million series in Prometheus and in Mimir, one backend
stayed under 1 GB of memory.

## What every backend must share

| What | Why |
| --- | --- |
| The same PostgreSQL database | It's the system of record, and it's where backends agree on who runs what. |
| The same Qdrant | Operational memory and similar-case search read it. |
| The same `OPS_SIGNALS_API_TOKEN` | Callers send one token, whichever backend answers. |
| The same `OPS_SIGNALS_SESSION_SECRET` (or the same API token, when it's unset) | The web UI sign-in cookie is signed with it. With different secrets, a user is signed out whenever the load balancer sends them to another backend. |
| The same connections file and config | A scheduled analysis can run on any backend, so each one must reach the same Prometheus or Mimir with the same settings. |

## What happens to background jobs

Every backend starts the same background jobs. This is what each one does when several backends
run:

| Job | With several backends | Duplicates? |
| --- | --- | --- |
| Scheduled analyses (saved schedules) | Before a run starts, the backend claims it in the database by moving its next run time forward. Only one backend's claim succeeds; the others skip that run. | No |
| OTLP analysis (points pushed to `/api/otlp/v1/metrics`) | Each minute, the backend that gets a database lock analyzes the waiting points; the others skip that minute. Every backend can still receive OTLP data. | No |
| Deploy discovery | Same: one backend at a time, by database lock. | No |
| Slack notifications and retries | Each message waiting to be sent is claimed by one backend. | No |
| Reference data at startup | One backend at a time, by database lock. | No |
| Operational memory catch-up | Every backend runs it. A case always gets the same entry in Qdrant, so the second one rewrites the same entry. | No, but the work is repeated |
| Stored point cleanup | Every backend with the scheduler on deletes points past the retention period, about once an hour. Two backends deleting at once delete the same rows. | No, but the work is repeated |
| Metric Usage check | The guard against two checks at once only works inside one backend. Two backends can both start a scheduled check at the same moment. | Possible: an extra check and twice the reads from Grafana and Prometheus |
| Jira ticket outbox | Each ticket operation is claimed with a lease, but two backends polling at the same instant can both claim the same one. Before creating an issue, the Jira adapter searches for one already made for that operation, which usually stops a second ticket. | Unlikely, not impossible |

The last two are why the recommended setup below runs these jobs on one backend.

## Recommended setup

Choose one backend to run the background jobs, and turn them off on the others:

| Backend | Settings |
| --- | --- |
| Job backend (one) | Defaults: scheduler and ticketing worker on. |
| Every other backend | `OPS_SIGNALS_AUTONOMOUS_SCHEDULER_ENABLED=false` and `OPS_SIGNALS_TICKETING_WORKER_ENABLED=false` |

The scheduler setting covers scheduled analyses, OTLP analysis, deploy discovery and the Metric
Usage check. The other backends still serve the UI and the API, receive OTLP data and Alertmanager
alerts, and run analyses that users start.

If the job backend is down, scheduled work waits until it's back. Nothing is lost: due schedules
run on its first tick, and OTLP points wait in the database. If you'd rather have the jobs keep
running while one backend is down, leave them on everywhere. The table above shows what that
costs.

## Limits are per backend

These limits are counted inside each backend, not across all of them:

| Limit | Setting |
| --- | --- |
| OTLP points per minute | `OPS_SIGNALS_OTLP_MAX_POINTS_PER_MIN` (default 60,000) |
| OTLP series per metric | `OPS_SIGNALS_OTLP_MAX_SERIES_PER_METRIC` (default 2,000) |
| Alert analyses at once | `max_concurrent_analyses` in the alert enrichment settings (default 4) |

With a load balancer in front of two backends, up to twice these amounts get through. Lower them on
each backend if the total matters.

## Upgrades

Each backend updates the database schema when it starts. After an upgrade, start one backend
first and wait until `/api/health` answers, then start the others.

## What you'll notice

- **"Next run" moves forward when a run starts,** not when it ends. When the run finishes, it's
  set again from the finish time, as before.
- **A backend that stops mid-run doesn't retry that run straight away.** The schedule runs again
  at its next interval, on whichever backend claims it first.
- **A run that takes longer than its own interval** can be started again by another backend
  while the first is still going. With intervals of 10 minutes or more this is unlikely; keep each
  schedule's interval longer than its runs take.
- **OTLP metrics come from one backend at a time.** `otlp_analysis_cycle_duration_seconds` and
  `otlp_analysis_cycle_groups_processed` change only on the backend that ran the last cycle.
  `otlp_points_received_total` counts on whichever backend received the data.
