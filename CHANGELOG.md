# Changelog

## 0.3.0 - Unreleased

- Added OTLP/HTTP metrics ingestion: `POST /api/otlp/v1/metrics` accepts pushed metrics (Gauge and
  Sum), with volume and cardinality limits, and the scheduler analyzes them on its normal cycle.
  `GET /api/otlp/status` reports what was received. See
  [`docs/design/otlp-metrics-ingestion-plan.md`](docs/design/otlp-metrics-ingestion-plan.md).
- Added Slack notifications for high-importance findings (`OPS_SIGNALS_SLACK_ENABLED`,
  `OPS_SIGNALS_SLACK_WEBHOOK_URL`, `OPS_SIGNALS_SLACK_MIN_IMPORTANCE`).
- Added alert enrichment: Alertmanager sends alerts to `POST /api/integrations/alertmanager` (or
  any tool to `POST /api/alerts`), and Ops Signals analyzes the alert's series and posts one Slack
  message with what happened, what changed and similar past cases. Change events such as deploys
  are recorded through `POST /api/events`. Off unless `OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED=true`.
  See [`docs/alert-enrichment.md`](docs/alert-enrichment.md).
- Added a one-command demo, `docker compose -f docker-compose.demo.yml up`, that starts with an
  incident already in progress. See [`docs/demo.md`](docs/demo.md).
- The API version now comes from `pyproject.toml`, so the package, the API and the release tag
  report the same version. It was fixed at `1.0.0`.
- Helm: images default to `ghcr.io/ramprasadgk9/ops-signals-*` at the chart's `appVersion`, and
  the database URL can come from a Secret (`database.urlSecret`). **Behavior change:** the URL
  moved from `backend.env` / `mcp.env` to `database.url`.
- **Behavior change:** `POST /api/testing/reset-operational-data` is gone unless
  `OPS_SIGNALS_ENABLE_TESTING_API=true`, and the endpoints that write files on the server (saving,
  promoting and deleting analyzers, generating adapter code, saving behavior definitions to a pack)
  return 403 unless `OPS_SIGNALS_ALLOW_FILE_WRITES=true`. The dev scripts turn both on, and the
  demo turns on file writes.
- Added an optional API token (`OPS_SIGNALS_API_TOKEN`) that protects every endpoint except
  `/api/health`. The alert and event receivers use it when they have no token of their own. The web
  UI's nginx adds it on the server side, the Grafana plugin has a field for it, and Helm reads it
  from a Secret.
- CORS origins are now configurable with `OPS_SIGNALS_CORS_ORIGINS`.
- Fixed: the behavior-definition `pack_file` accepted paths, so a request could write YAML outside
  `config/behavior_definitions.d/`. It must now be a bare `.yml`/`.yaml` file name.
- Fixed: an analyzer's display name and library went into the generated adapter code unescaped,
  so a crafted name could inject code that ran when the adapter was imported.
- Added [`docs/security-model.md`](docs/security-model.md).
- Renamed `OPS_INTEL_DATABASE_URL` to `OPS_SIGNALS_DATABASE_URL`, so every setting uses the same
  `OPS_SIGNALS_` prefix. The old name still works, and the new one wins when both are set.
- The API now calls itself "Ops Signals API" (it was "Ops Intelligence API").
- Analyzers added through the Add Analyzer wizard now run on scheduled (autonomous) runs too.
  Those runs used to build only the 7 built-ins from a hardcoded list; they now read
  `config/analyzer_registry.d/` like CSV runs do.
- Analyzers added through the wizard now appear in the Recommendations view, MCP and the AI
  second opinion. The recommendation service used to skip `config/analyzer_registry.d/`.
- Added two registry options for guard-style analyzers, also available as wizard switches:
  `accepts_flat_or_gappy_series` (don't reject flat, gappy or zero-variance series) and
  `always_run` (run outside the `max_analyzers` limit). Scoring rules can now use
  `constant_value_percentage`.
- Added the `data_health` analyzer (`config/analyzer_registry.d/custom_data_health.yml`), which
  reports a metric that stopped reporting (`data_gap`) or got stuck at one value (`flatline`). It
  runs on every analysis and only reports stretches that are unusual for that metric, so sparse or
  constant-by-design metrics stay quiet. Its signals become a separate `data_quality` finding
  rather than joining the metric's behavior finding. On Prometheus runs (scheduled and direct) it
  also reports a metric that went silent before the end of the query window, as an ongoing
  `data_gap`; CSV uploads and OTLP pushes have no window end, so that check is off there. Gaps
  longer than the provider's `max_gap_minutes` still fail the upload before any analyzer runs.
- Added the `seasonal_anomaly` analyzer (`config/analyzer_registry.d/custom_seasonal_anomaly.yml`),
  which flags values that are unusual for their time of day or week - e.g. 3am traffic at a
  daytime level - using STL decomposition and a MAD-based robust z-score. It needs at least 3 days
  (or 3 weeks) of data with a daily (or weekly) cycle and stays silent otherwise.
- Added `calendar_seasonality_strength` to the router's series profile: how strongly a series
  repeats daily or weekly. The existing `seasonality_strength` reads a smooth daily cycle as noise,
  so it scored 0 on typical daily traffic; the new measure is used only by `seasonal_anomaly`'s
  scoring, so no other analyzer's routing changes. Wizard scoring rules can use it.
- **Behavior change:** on a series with a strong daily cycle, `seasonal_anomaly` now wins one of
  the router's execution slots. Across the benchmark and sample datasets this changed two
  scheduled-run results: on `cpu_complex_forecast_v1` it replaces `stumpy` (findings unchanged),
  and on `cpu_seasonal_forecast_v1` it replaces `trend`, so the finding now reads "predictable
  recurring or forecastable behaviour" instead of "trending in one direction", matching the
  scenario's ground truth.
- Fixed: the Autonomous Monitoring overview stayed on "No autonomous analysis has been completed
  yet" even while scheduled runs were completing. It only showed a manual "Run once" from the same
  page, and once a scheduled policy is saved that button is no longer shown. It now shows the
  latest finished scheduled run - its metric counts, run history, and the findings and cases from
  that run's analyses - while a manual run in the page still takes priority.
- Fixed: `data_health` reported false "stuck" flatlines on the local mock metrics - `error_rate`
  parked at its 0.006 floor while CPU was low, and `rate(promhttp_metric_handler_requests_total[5m])`,
  which is constant apart from float jitter. A flat stretch is no longer reported when the metric
  sits at exactly that value at other times and it is the metric's floor or ceiling, or when the
  series only jitters around one level. Real stalls - a counter that stops increasing, a gauge
  that freezes at its latest high, a value stuck mid-range or beyond its usual range - are still
  reported.
- Fixed: Ask Ops Signals only knew about 4 analyzers (a fixed list), and described any other one
  as a baseline-shift analyzer. It now builds its analyzer knowledge from the analyzer registry, so
  every analyzer that can run - including `data_health`, `seasonal_anomaly` and ones added through
  the Add Analyzer wizard - gets an accurate description.
- Ask Ops Signals routing: naming an analyzer (e.g. "seasonal_anomaly", "data health") leads with
  that analyzer's documentation; data-quality and time-of-day phrasing ("stuck", "stopped
  reporting", "time of day") also searches findings; "How does X work?" now searches for X instead
  of returning the architecture overview; and when no documentation matches a question, the generic
  fallback documentation is listed after real findings or cases instead of leading the answer.
- Fixed: after a CSV upload on New Analysis, Router Decisions said "Executed analyzers: none" and
  marked every analyzer "execution unavailable", because the page dropped the execution details
  the backend returned. It now shows which analyzers completed or were skipped, and why.
- Fixed: on a scheduled run, an analyzer that raised an error crashed the run with a `NameError`
  instead of being recorded as failed.

## 0.2.0 - 2026-09-14

- Let a Behavior Finding (a correlated, cross-metric pattern) be promoted to a Case, not just a
  single-metric Finding - behaviors previously had no path to an RCA, resolution, or recorded
  outcome at all.
- Added `GET /api/alert-context`: a single lookup an external alert manager can call before firing
  an alert, combining exact-match learning-outcome history, semantically similar resolved cases,
  and raw finding/behavior recurrence (patterns that occurred but were never cased) into one
  recommendation - with an optional AI-polished summary that falls back to a deterministic
  sentence whenever AI is off or fails.
- Fixed: resolving a case as "Resolved" failed silently - the Resolution tab had no field for the
  required `learning_outcome_status`, so the save request was rejected with no visible error and
  the case's outcome was never actually recorded.
- Fixed: repeated analysis runs on the same data produce findings/behaviors with byte-identical
  auto-generated titles - the alert-context "raw activity" list now shows distinct titles instead
  of the same sentence repeated.
- Replaced the hardcoded analyzer if/elif chain with a config-driven registry
  (`config/analyzer_registry.d/`) that merges custom registrations additively, never overriding a
  built-in analyzer. Reworked the Add Analyzer wizard to write to this backend, collapsed its
  workflow from 5 steps to 3, and added a two-track Python/API entry choice for new contributors.
- Wired the autonomous monitoring results dashboard onto the configure page - "Run Once" now shows
  what the run actually found instead of a one-line status banner.
- Gave the "Ask Ops Signals" assistant real retrieval and optional local LLM synthesis: automatic
  case indexing, semantic search over findings/behaviors, LLM-assisted routing that only adds
  coverage on top of deterministic keyword routing (never replaces it), and an opt-in local Ollama
  service (`docker compose --profile ai up`, no API key, no cloud calls). Every answer now labels
  whether it came from a model or a template.
- Added a benchmark suite covering detection accuracy (not just router recommendation), a
  false-positive negative control, opt-in router precision checks, and the first multi-metric
  Behavior Intelligence scenarios. See `benchmark/README.md` and `benchmark/CONTRIBUTING.md`.
- Fixed the assistant's document retrieval: ADR files were silently invisible to search (a
  non-recursive glob skipped `docs/adr/`), and documents over 8,000 characters - including
  README.md itself - were truncated rather than fully searchable. Long documents are now chunked
  instead.
- Documentation and governance structure added; operational intelligence architecture clarified;
  PostgreSQL and Qdrant responsibilities documented.

## 0.1.0

- Initial project scaffold
