# Changelog

## Unreleased

- **Fixed: Metric Usage ignored Grafana with `docker-compose.packaged.yml`.** The packaged compose
  didn't pass `OPS_SIGNALS_GRAFANA_*` or `OPS_SIGNALS_METRIC_USAGE_*` from `.env` into the backend
  container, so setting them did nothing and Metric Usage counted only Prometheus rules. They are
  passed now; the README says a Grafana on the same machine is `http://host.docker.internal:3000`
  from inside Docker, and where the settings go with Helm.
- **SECURITY.md and CODE_OF_CONDUCT.md say how to report**: vulnerabilities through GitHub's
  private vulnerability reporting, conduct problems privately to the maintainer.
  docs/release-process.md explains why the project (0.x) and the Grafana plugin (1.0.x) have
  different version numbers.
- **Fixed: `docker compose -f docker-compose.packaged.yml up -d` stopped at "dependency qdrant
  failed to start".** Qdrant's health check called `curl`, which the current `qdrant/qdrant` image
  doesn't include, so Qdrant never counted as healthy and the backend, web and MCP containers
  never started. The check now opens the port with bash instead, as `docker-compose.demo.yml`
  already did; `docker-compose.yml` had the same check and is fixed too.
- **Python 3.12 is the recommended version** (README): it's what the Docker images and CI use;
  3.11 and 3.14 still work. `scripts/setup.sh` and `scripts/bootstrap_sample.sh` pick 3.12 when
  it's installed, and keep the version an existing `.venv` already uses instead of rebuilding it.
  CI now also checks that every Python file compiles on 3.11 and 3.14.
- **Fixed: the finding-trust benchmark report didn't run on Python 3.11.**
- **Fixed: resetting operational data (`/api/testing/reset-operational-data`) left the "Was this
  real?" answers behind**, so old answers kept moving new findings between lists.
- **The RCAEval download is now verified** against a pinned SHA-256, like every other benchmark
  dataset; a file that doesn't match is refused.
- **Dark mode in the web UI.** The moon/sun button in the top bar now switches the whole UI, not
  just its icon: pages, cards, tables, inputs, status boxes and chart tooltips follow it. The choice
  is remembered in the browser, and until you choose, the UI follows your system's light or dark
  setting. The Grafana plugin keeps Grafana's own theme.
- **Finding trust: each finding says how often findings like it were real, and only the ones that
  earned it ask for attention** (see `docs/finding-trust.md`). The Findings page now has a
  **Needs attention** list and a folded **Context only** list. A lasting level change seen by two
  different checks is **Strong evidence** (91% real in tests, against 60% for a random alert, 266
  checked); seen by the change check alone it is **Moderate evidence** (70% against 57%); a metric
  that stopped or froze is a **Data problem**. Single unusual values, patterns and forecasts move to
  Context only: in tests they were real about as often as a random alert. Each card shows **On your
  service** next to **In testing**, and a **Was this real?** answer (real problem, expected change,
  not a problem) builds the service's own number, which takes over after 5 answers. With 5 or more
  answers, a service's own answers also move a kind of finding between the lists on that service:
  context findings real at least half the time move up (**Confirmed by your team**), needs-attention
  findings real less than 1 in 5 times move down (**Usually not a problem here**); data problems
  never move down. The tested
  numbers come from a new benchmark (`benchmark/finding_trust`) on RCAEval's 375 injected
  microservice faults and NAB's cloud-server metrics, kept in `config/finding_trust.yaml`. The
  badge replaces the importance-based level on the card, because importance didn't separate real
  problems from noise in the tests. New: `POST /api/findings/{id}/feedback`, a `trust` object on
  findings, and the `ops_finding_feedback` table (created at startup).
- **Metric Usage: which metrics a dashboard or alert watches, and the problems nobody would see**
  (new **Metric Usage** page; on once `OPS_SIGNALS_GRAFANA_URL` and a read-only Viewer token are set,
  see README "Metric Usage"). Every 6 hours it reads Grafana dashboards (library panels, collapsed
  rows and `$variables` included) and alert rules plus Prometheus/Mimir alerting and recording rules,
  takes the metric names from their queries, and compares them with every metric in each Prometheus
  connection and with recent findings. Each metric lands in one group: **blind spot** (on no
  dashboard or alert, with recent significant or critical findings; links to the finding and can
  become a case), **missing** (a panel or alert reads a metric that isn't there), **watched**
  (directly or through recording rules) or **not watched**. The page opens with the unused share of
  stored series, the problems nobody would have seen and how coverage moved since the oldest kept
  check; **Run now** checks without waiting. Unused series show as a monthly cost only when you set
  your own rate (`OPS_SIGNALS_METRIC_USAGE_COST_PER_1K_SERIES`); there is no built-in price. Finding
  cards say which dashboard or alert shows the metric, and the Overview names blind spots. With
  several connections a Grafana datasource counts only on the connections with its URL, or those
  naming it under the new `grafana_datasources` field of the connections file; panels on a
  datasource that matches none are left out with a warning. Excluded folders, ignored metrics and
  the interval are in `.env.example`.
- **Fixed: metric names read from a query included `offset 5m`, `1e3`, Grafana `$variables` and
  `# comments`** as if they were metrics. Alert enrichment shares this code.
- **Your own Prometheus or Mimir from the first install**: the Quick Start has an optional step for
  `.env` - one Prometheus URL, or a connections file for several Mimir tenants or Prometheus servers
  - and the Prometheus section says what changes when you switch later (policies made before keep
  working). `scripts/run_all.sh` no longer starts the bundled Prometheus and mock metrics once
  `.env` points at your own; `OPS_SIGNALS_LOCAL_PROMETHEUS=true` starts them anyway, and they still
  start with alert enrichment on, for its demo rules.

## 0.3.0 - 2026-10-07

- **Jira ticketing for cases** (Jira Cloud; off by default, `OPS_SIGNALS_TICKETING_ENABLED` and the
  `OPS_SIGNALS_JIRA_*` settings in docs/configuration.md). A case's **External Ticketing** card
  creates one Jira ticket from it, with the summary and evidence. Requests go through a background
  outbox with retries, so a slow or failing Jira never holds up the case; when Jira's answer is lost
  mid-create, the card asks whether to check Jira again, link the ticket that was made, or create a
  new one, instead of risking a duplicate. **Sync Now** brings the ticket's comments and status into
  the case, **+ Add to Notes** keeps a comment as a case note, **AI Triage** (with an AI provider
  configured) promotes the useful comments on its own, and **Sync Resolution to Jira** posts the
  cause and fix on the ticket and moves it to Done. Jira webhooks
  (`POST /api/integrations/ticketing/jira/webhook`) sync without Sync Now; they need
  `OPS_SIGNALS_JIRA_WEBHOOK_SECRET` and unsigned deliveries are refused. The Grafana plugin shows
  the same ticket section on a case. Tested against a Jira Cloud project. New tables come with
  `backend/migrations/008_case_ticketing_integration.sql`.
- **"Watch how" for Jira ticketing on the case page**: a one-minute captioned recording of the real
  case page - create the ticket, sync a Jira comment and status back, keep the comment as a note,
  send the resolution to Jira, webhook setup. The External Ticketing card links it from its header.
  While ticketing is off, a blue banner at the top of the Cases list and of every case says Jira
  ticketing exists, with Watch how and How to turn it on (the settings). It can't be dismissed, so
  everyone sees it; once ticketing is on it gives way to the case's External Ticketing card. A
  finding's Create Case button says on hover that a Jira ticket can be created from the case, and
  a case now always opens at its top (it kept the scroll position of the page the click came from,
  so the banner could be off screen). How to turn it on says how to restart the backend for a
  laptop install, a team server and Kubernetes.
- **Fixed: Jira ticketing could not be turned on with `docker-compose.packaged.yml`.** It passes
  only the settings it lists to the backend, and the Jira ones were missing; they now come from
  `.env` like the others (ticketing stays off unless set).
  Re-recorded by `scripts/record_jira_walkthrough.sh` against the demo stack and a Jira Cloud
  project. Also fixed: the card's header buttons ran out of the card in narrow windows; they wrap now.
- **Monitoring coverage** on Operational Memory: each imported past incident checked against what
  Ops Signals analysed and flagged while it happened - **Detected** (a finding on that service, with
  an anomaly overlapping the incident, reads like the postmortem's symptom), **Flagged something
  else** (shown by title, to judge), **Missed** (the service was analysed and nothing was flagged: a
  detection gap) or **Not watched** (nothing analysed the service then: a coverage gap). A miss also
  says whether the same problem has been detected on that service at another time. Counts, a bar
  per service, and the gaps listed first. `GET /api/memory/coverage?days=`.
- **Seen before? in the Grafana plugin**: the interactive result (below the selected finding) and
  the autonomous Evidence / Investigation panel now list past cases from operational memory that
  look like the finding - same service first, other services folded away, each with strong or
  possible match, score, cause and fix, and the familiarity badge (New pattern / Seen before /
  Recurring). Same endpoint and ordering as the web UI (`GET /api/findings/{id}/seen-before`).
- **Fixed: cases in the Grafana plugin's Recent Cases from History did nothing when clicked.** A
  click now opens the case in the plugin's case workflow drawer (Finding → Investigation → Root
  Cause → Resolution → Publish Knowledge), the same one Interactive Analysis uses, with the Finding
  step read from the case's stored snapshot. The list refreshes on close when something was saved.
  Save failures now also show inside the drawer.
- **Schedule card (Grafana plugin and web UI)**: **Remove** is now **Pause**, which is what it
  always did (the schedule is kept and shows Resume), and **View Overview** is gone - in the plugin
  the Overview tab above the card opens the same page, and in the web UI the overview is directly
  below the card (the button only scrolled to it, and was easy to confuse with the sidebar's
  Overview page).
- **Removed: the Experiments page** (`/experiments`, "Analyzer Experiment Dashboard") and its API
  (`GET /api/experiments`, `/api/experiments/{id}`, `/api/experiments/compare`). It only listed
  result files from the offline ruptures script and wasn't tied to live data; the Analyzer Labs
  cover trying an analyzer on data. `/experiments` now redirects to the Ruptures Change Point Lab.
  The script (`experiments/ruptures/run_experiment.py`) still runs and writes its reports.
- **Symptom and fix vectors**: each case in Qdrant now has a `symptom` vector (what was seen) and a
  `resolution` vector (cause and fix, once recorded) next to the whole-document one. Seen before?
  and Similar Cases compare a finding's symptom with past symptoms, so an imported postmortem about
  the same problem as a detected finding is now usually a **strong** match (0.57 → 0.77 on the test
  catalogue) while unrelated cases stay low. Alert messages and chat questions still search the whole
  document, so a cause named in an alert ("db connections maxed out") still ranks that case first.
- **Did the fix hold?** is inferred: a fix held if no case with the same symptom was opened on the
  same service within 30 days; otherwise it **came back after N days**; before 30 days it is **too
  early to tell**. Shown in **Same fix elsewhere** on a case's Similar Cases tab (other incidents,
  on any service, resolved by the same cause and fix: `GET /api/cases/{id}/same-fix`) and in
  **What fixed this before** on a finding's Seen before? (past fixes merged where they say the same
  thing, ranked by how often they held: `GET /api/findings/{id}/suggested-fixes`). **Draft a
  runbook** writes numbered steps from those fixes, citing the cases, with the configured LLM; it is
  a draft and never saved (`POST /api/findings/{id}/suggested-fixes/runbook-draft`).
- **Recurring problems** can group **by cause** as well as by symptom, and are drawn rather than
  listed: a ranked bar per problem (how often it happened; click to jump to it) and a timeline per
  problem with a dot for each occurrence - still open, fixed with a verified cause, or fixed without
  one - linking to its case. Causes show the first two, the rest one click away.
- Repeats of the same incident (same service, symptom, cause and fix) fold under one match as **+N
  more like this** on Similar Cases and Seen before?, so one recurring incident can't fill every
  slot; Slack says "+N more like this"; the assistant lists each past problem once.
- The `operational_cases` collection is recreated once on startup with the new vectors (points kept,
  the old vector becomes `full`), and the new vectors are filled in from PostgreSQL in the
  background; until then symptom searches use the whole document.
- **Recurring problems** on Operational Memory: past cases from the last 30, 90, 180 or 365 days
  grouped into the problems that keep coming back ("6 times in 90 days"), with the services, how
  many causes were verified, how many cases are still open, and the causes and fixes found each
  time. Groups come from Qdrant's distance matrix; every case in a group is at least 80% like the
  group's central case, so loosely related cases don't chain together. With an LLM configured the
  groups are named by it, otherwise after their central case. `GET
  /api/memory/recurring-problems?days=&min_occurrences=`.
- **New pattern / Recurring badge** on a finding's Seen before? and a case's Similar Cases: **New
  pattern** (nothing in memory looks like it), **First time on <service>** (only other services
  have had it), **Seen before**, or **Recurring · N past cases** (3 or more on the same service).
  Counted from the matches already shown, so no extra search runs; returned as `novelty` on both
  APIs.
- Recall ranks past cases on exact words and context, not only meaning. Each case is indexed in
  Qdrant with a keyword vector next to its embedding, so a past case naming the same error, service
  or metric (`OOMKilled`, `5xx`, `checkout-api`) ranks above one that is only about something
  similar. Matches are then ordered by similarity plus small bonuses for the same service, a
  verified root cause and recency - at most 0.25 together, so a much more similar case always stays
  on top. Applies to Similar Cases, Seen before?, alert context and Slack enrichment, Ask Ops
  Signals and MCP memory chat. Shown similarity, the strong/possible labels and score thresholds are
  unchanged. The keyword vector arrives with the one-time collection migration described above; if
  the ranking query ever fails, recall falls back to plain similarity.
- Cluster-aware deploy events: `POST /api/events` takes an optional `cluster`, and `GET
  /api/events` filters by it. A finding or an alert is matched only to change events from its own
  cluster, or with no cluster (a deploy everywhere, or a single-cluster setup), so a deploy to `eu`
  is no longer shown as "After deploy" on a `us` finding. The UI and Slack name the cluster ("deploy
  v1.4.2 to us"). The `ops_change_events.cluster` column is added on startup. The local multi-cluster
  setup gives `checkout` in `us` pods replaced by each release, and `./scripts/multicluster.sh
  deploys` posts the matching deploys.
- Findings page: search by service, metric, cluster, connection or finding number (`#57`), sort by
  latest (the new default), oldest, importance or investigation priority, and every finding in the
  window is listed, 20 at a time - before, only the 5 most important were shown. Search and sort are
  kept in the URL (`?q=`, `?sort=`). A `#number` outside the window can be opened directly. New
  Analysis results show the finding number and link to it with **View in Findings**. A finding that
  repeats across runs (same connection, service, metric, cluster, category and title) gets one card
  with a **Seen in N runs** chip, giving the first and latest time; clicking it lists each run, and
  **Group repeats** turns grouping off (`?group=off`).
- Finding levels read as importance: `critical`, `significant` and `normal` are shown as **High**,
  **Medium** and **Low** (grey, no longer a green "Normal" that looked like "all fine"), with a
  tooltip giving the score range. Stored values and the API are unchanged.
- Validate Data asks for a **Cluster** when the chosen service and metric exist in more than one
  cluster, before running, instead of failing with "returned 2 series".
- Named Prometheus connections, one per Mimir tenant. List them in a YAML or JSON file named by
  `OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE`, each with its own URL, tenant header, auth and cluster
  settings; secrets come from `${ENV}` references. Every Prometheus API call takes a `connection_id`;
  an unknown id is a 404, never a silent fallback, and `default` still means the default connection.
  The Configure panel and Validate Data get a **Prometheus connection** picker when there is more than
  one. Autonomous policies keep their connection, and a scheduled run for a removed connection fails
  instead of querying another tenant. Alerts are analysed on the connection whose `match_labels` they
  carry (otherwise the default), and never reuse a finding from another connection. Findings carry
  `connection_id`, shown on cards and in the drawer. The Integrations status lists each connection's
  reachability. A broken connections file stops startup. Without the file, the
  `OPS_SIGNALS_PROMETHEUS_*` variables give one `default` connection, as before. New
  `analysis_runs.connection_id` and `autonomous_policies.connection_id` columns are added on startup.
  Docker Compose takes the file through the new `docker-compose.connections.yml` overlay, and the Helm
  chart through `prometheusConnections` (file in a ConfigMap, tokens from a Secret); a starting file
  is in `examples/prometheus-connections.yaml`. `docker-compose.packaged.yml` now reads
  `OPS_SIGNALS_PROMETHEUS_URL` from the environment instead of hardcoding `http://prometheus:9090`.
  The README's Quick Start says which way to run Ops Signals (demo, laptop, Docker Compose, Helm),
  with a new **Deploy for Your Team** section.
  See [`docs/standalone-prometheus-analysis.md`](docs/standalone-prometheus-analysis.md#several-tenants-named-connections).
- Multi-cluster Mimir and Thanos. When one endpoint holds several clusters' data, series that differ
  only by the `cluster` label are now analysed separately instead of being added together. Autonomous
  analysis plans one job per cluster (`by (service, cluster)` with a `cluster="…"` matcher), and the
  Configure panel gets a **Clusters** picker when there is more than one cluster. Findings, signals
  and stored points have a `cluster` field: cards and the details drawer show it, the Findings page
  can filter by it, and `GET /api/findings?cluster=` filters too. An alert from one cluster never
  reuses another cluster's finding. HA replica pairs count once: autonomous queries wrap series in
  `max without (__replica__, prometheus_replica)`, and previews, direct analysis and alert analysis
  keep one copy and say how many were dropped. Labels are set with
  `OPS_SIGNALS_PROMETHEUS_CLUSTER_LABEL` and `OPS_SIGNALS_PROMETHEUS_REPLICA_LABELS`. Data without
  these labels is analysed exactly as before. The new `cluster` columns are added on startup. See
  [`docs/standalone-prometheus-analysis.md`](docs/standalone-prometheus-analysis.md#mimir-thanos-and-other-multi-source-backends).
- HTTP analyzers. An analyzer can now be your own web service: Ops Signals POSTs each metric window
  to it and shows the findings it returns next to the built-in analyzers'. Add one with **Add
  Analyzer → I have a hosted API or model** (no longer "coming soon") or an `http:` block in
  `config/analyzer_registry.d/`. Execution Test calls the health check and the service. If the
  service is down or slow, that run lists the analyzer as failed and the other analyzers still run.
  API keys are read from an environment variable named in `api_key_env`. Built-in analyzers and
  Python custom analyzers are unchanged, and nothing is called unless you register a service. See
  [`docs/http-analyzer-contract.md`](docs/http-analyzer-contract.md), with a runnable example in
  `examples/http_analyzer/service.py`.
- AI provider choice. Besides Ollama, the optional AI layer can now use any OpenAI-compatible
  endpoint (`OPS_SIGNALS_AI_PROVIDER=openai_compatible`: vLLM, Azure OpenAI, Bedrock gateways,
  LiteLLM) or Anthropic (`anthropic`, default model `claude-opus-5`). AI is still off by default and
  everything works without it; a misconfigured provider logs a warning and falls back to no LLM.
  Adds the `anthropic` package as a dependency. **Integrations → AI provider** shows whether AI is
  in use, which provider and model, why not when it's configured but not running, and a **Test
  connection** button (`GET /api/ai/status`, `POST /api/ai/test`). See
  [`docs/ask-ops-signals-assistant.md`](docs/ask-ops-signals-assistant.md#other-ai-providers).
- Prometheus-compatible backends (Thanos, Mimir, VictoriaMetrics, Grafana Cloud) work more reliably
  ([#67](https://github.com/ramprasadgk9/ops-signals/issues/67)). Autonomous discovery now asks
  only for series seen in the policy's analysis window instead of all history, so long-retention
  backends answer quickly and old series no longer use up "Max metrics per run". The Configure
  panel's Service/Namespace lists show values seen in the selected window
  (`GET /api/autonomous/scope-options?window=24h`). Errors now include the backend's own message
  (e.g. "Prometheus HTTP error: 422: the query exceeded the maximum number of series") instead of
  only the status code. Warnings in a response, such as partial data from an unreachable Thanos
  store, are shown on the preview, run and job instead of being dropped. The connection test no
  longer fails on backends that don't serve `/api/v1/status/buildinfo`; it falls back to a trivial
  query. Series and range queries longer than 2 KB are sent as a POST form so gateways don't reject
  them with 414.
- Import past incidents. A new install's memory is empty, so "have we seen this before?" found
  nothing for months. Postmortems and incidents can now be imported from Jira or PagerDuty CSV
  exports, any CSV, or Markdown postmortems (also as a `.zip`), as resolved cases that similar-case
  search and alert enrichment match from day one. Use **Import past incidents** on Operational Memory,
  the **Incident history** card on Integrations, `ops-signals import-cases <folder>`, or
  `POST /api/case-imports`. The preview shows what each record will do before anything is written.
  Re-importing never duplicates: records are keyed by source and ID, unchanged ones are skipped and
  changed ones update their case in place, keeping notes added in Ops Signals. Emails, IPs and
  common secrets are masked before storage, and a whole import can be undone. Imported cases carry
  an **Imported** badge, skip learning outcomes, and are recalled on service since they have no
  metric. Adds columns to `ops_operational_cases` and an `ops_case_imports` table, applied at
  startup (`backend/migrations/007_imported_cases.sql`). See
  [`docs/importing-incident-history.md`](docs/importing-incident-history.md).
- Past cases are visible where you look first. A finding's details now have a **Seen before?**
  section listing past cases (detected or imported) that look like it, without opening a case; it
  is backed by the new `GET /api/findings/{id}/seen-before`. Similar Cases and Seen before list
  same-service matches first, fold other services away, and mark each match **strong** (70%+) or
  **possible** (40-70%); Similar Cases previously hid everything under 70%, which hid every imported
  postmortem from a detected case. When an alert has no outcome history but matches past incidents,
  the alert preview and Slack message say **Seen before** with the closest incident's cause and fix
  instead of "not enough history".
- Findings show the deploy before their change. Deploy events from `POST /api/events` are looked up
  when a finding is shown, so findings from scheduled runs (not only alerts) get an "After deploy
  v1.4.2" chip and a **What changed** line. When the pod breakdown has new pods that first
  reported within `OPS_SIGNALS_DEPLOY_ROLLOUT_WINDOW` (default 15m) after the deploy, it says "These
  2 new pods started with deploy v1.4.2" and the next step points at that version. Every case
  without data (no deploys recorded, none near the change, no start time, lookup failed) shows a
  plain reason, and the finding itself is never affected. New `OPS_SIGNALS_SERVICE_ALIASES` joins a
  CI service name to the metrics' service label, for findings and alerts. `GET /api/findings`,
  `/api/findings/search` and `/api/findings/{id}` return a new `changes` field. See
  [`docs/finding-drilldown.md`](docs/finding-drilldown.md#which-deploy-started-the-new-pods).
- Fix: finding details showed "0 supporting signals" for a finding opened from a link (e.g. an
  alert) when it was outside the Findings page's list, and counted diagnostic-only signals.
- Fix: finding cards showed "0 supporting signals" on a long list (e.g. Last 7 days). The page
  fetched signals with one request per analysis run (thousands for a week), and every card stayed
  at 0 until all of them finished, or for good if one failed. `GET /api/signals` now takes
  `analysis_run_id` repeated, and the page asks for 100 runs per request.
- Alert messages say which pods a change came from. With `OPS_SIGNALS_DRILLDOWN_ENABLED=true`,
  alert-triggered analysis runs the same pod drill-down as autonomous runs and adds a "📍 Where"
  line, e.g. "2 of 6 pods rose: checkout-5, checkout-6 … looks like a rollout in progress". A
  reused autonomous finding keeps its breakdown. See [`docs/finding-drilldown.md`](docs/finding-drilldown.md).
- Fix: alert enrichment reused a finding from an earlier alert's analysis of the same service and
  metric, so an alert that fired again within 30 minutes skipped fresh analysis and claimed Ops
  Signals "detected this N min before". Only findings from autonomous analysis are reused now.
- "What changed" timing: a change point counts as a step change only if the metric stays shifted
  after it. A short spike that has already ended, which change-point analyzers also mark, is
  treated as a spike, so the message no longer calls it a step change.
- Drill-down: a pod with fewer than 3 points before the change counts as new. Before, a pod that
  came up a scrape or two before the detected change point was compared with its own couple of
  post-rollout points and reported as unchanged.
- New **Alerts** page (`/alerts`, after Overview in the menu) for received alerts; the Overview's
  "All alerts" link goes there. **Integrations** is now only about connecting sources: a new **Send
  deploy events** tile (URL, a ready-made `curl` step for CI, the last deploy received), and the
  Prometheus tile shows its URL (without credentials), whether it answers, and what uses it
  (autonomous analysis policies, alert enrichment). OTLP activity (points received, awaiting
  analysis, rejections) moved into the OTLP tile and shows once points arrive, instead of a
  separate card of zeros. "Just exploring?" stays on the Overview's first-run panel; Integrations
  mentions it in one line. `GET /api/ingestion/status` returns the new
  `events` source and the Prometheus details. `.env.example` explains deploy events in a section of
  their own.
- The alerts panel (Alerts and Overview) shows each alert's "Where" (pods) and "What changed"
  (deploys, worded like the Slack message) and marks deploys on the timeline. `GET /api/alerts`
  returns `timing`, `changes`, `change_window_before_minutes`, `service_has_change_events` and
  `breakdown` for this.
- New `scripts/demo_live.py`: a live demo next to `run_all.sh`, with per-pod metrics changed on
  demand and real alerts through Alertmanager. See [`docs/live-demo.md`](docs/live-demo.md).
  `OPS_SIGNALS_ALERT_MIN_STEP` sets the smallest query step for alert analysis (default 30s).
- **Behavior change:** the alert message's "What changed" section now times change events from
  the pattern the analyzers found. A step change or a spike gives a start time ("Spike started
  2 min after deploy `v4.1`"). A slow trend, or no analysis, gives none: nearby changes are listed
  for reference, timed from when the alert fired, with no "started after" claim. Previously a
  slow trend was timed from the alert, so a deploy minutes before it read as if it started a
  problem that had been building for hours. Change events from another environment than the alert
  are now skipped. New settings: `OPS_SIGNALS_ALERT_STEP_LOOKBACK`, `OPS_SIGNALS_ALERT_SPIKE_LOOKBACK`,
  `OPS_SIGNALS_ALERT_CHANGE_WINDOW_BEFORE`, `OPS_SIGNALS_ALERT_CHANGE_WINDOW_AFTER` and
  `OPS_SIGNALS_ALERT_MATCH_ENV`. See [`docs/alert-enrichment.md`](docs/alert-enrichment.md#how-changes-are-timed).
- **Behavior change:** a series with a timestamp gap over the provider's `max_gap_minutes` is no
  longer refused. It is analyzed, the gap becomes empty resampled buckets that `data_health`
  reports, and the message is logged and kept on the normalized frame. Real sensor and traffic
  feeds have multi-hour outages: under the old behavior, 18 of the 58 series in the Numenta
  Anomaly Benchmark were rejected before analysis. Set `gap_policy: reject` under a provider's
  `validation:` to keep the old behavior.
- `python -m benchmark.run_all` runs every benchmark suite and writes a local, gitignored snapshot
  to `benchmark/results/`, with a detailed HTML evidence report, the raw results, and a manifest
  of the commit, library versions and input hashes. An accuracy fingerprint that excludes timings
  shows whether a rerun reproduced the same results. The new `nab` suite runs all 58 NAB series
  through the production path in a causal replay mode and a batch mode, scores them against NAB's
  labeled windows, and writes NAB-format files for NAB's own scorer. See
  [`benchmark/README.md`](benchmark/README.md).
- New `tcpd` benchmark suite: change-point detection on the Turing Change Point Dataset, scored
  with the paper's F1 and covering against the 14 methods published with it, on the same series.
  The ported metrics are checked against all 1,014,504 published scores on every run.
- Ask Ops Signals answers documentation questions from the section that holds the answer, quotes
  that passage word for word, and cites it (`docs/security-model.md#turning-on-authentication`).
  Docs are indexed one Markdown section per chunk - chunks used to run to 6,000 characters, but
  the embedding model reads only about the first 1,000. Documentation sources now carry
  `source_path`, `section` and `quote`. With AI on, the model must quote its evidence, and a
  quote not found in the evidence is dropped. Also fixed: the project README was never indexed
  (its id collided with `docs/README.md`); MCP and API clients found less documentation than
  the web UI (they sent a stricter `minimum_score`); and questions routed to cases or findings,
  or mentioning "Ops Signals", never searched documentation. New golden question benchmark:
  `python -m benchmark.assistant_benchmark`; see
  [`docs/ask-ops-signals-assistant.md`](docs/ask-ops-signals-assistant.md#quality-benchmarking).
- New or edited docs can be picked up without a restart: **Reindex docs** on the Ask Ops Signals
  page (or `POST /api/assistant/knowledge/bootstrap`) re-embeds only documents that were added,
  changed or removed, and reports which. Startup does the same, so a restart with no doc changes
  no longer re-embeds the whole corpus (about 3 s to 50 ms). `force=true` re-embeds everything.
- Ask Ops Signals shows when docs changed since it last read them (a count on Reindex docs and a
  banner naming them), explains what reindexing is for, and asks "Did this answer your question?"
  under every answer - a thumbs-down records why.
- New **Docs check** page (`/assistant/docs-check`): see which docs have no golden questions, draft
  questions for them (with AI or from headings), ask each and see which section the assistant
  cited, and save the good ones - or the failing ones, as known gaps - to the golden set. Thumbs-down
  questions are listed there too. Saving needs `OPS_SIGNALS_ALLOW_FILE_WRITES=true`.
- The Ask Ops Signals first screen's "About your systems" examples now name this install's own
  findings, cases and services, so each one finds evidence when clicked. With nothing analysed yet
  it offers Load demo data and Connect a source instead of questions that came back empty.
- Ask Ops Signals answers lead with the right evidence and repeat nothing: quoted titles no
  longer steer routing, "did any metric stop reporting?" leads with findings, "Which analyzers are
  there?" lists every analyzer with what it finds (from the registry), a named service limits the
  findings searched, docs are no longer listed twice, past cases no longer repeat as Operational
  Memory, and design plans rank below user docs. Next steps and follow-up questions now match what
  leads the answer (no "Show the RCA for <a doc>").
- The backend and MCP images now include `README.md`, so Ask Ops Signals answers from it in Docker
  too; it was only indexed on local installs.
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
- The Overview page now shows a "Get data in" panel until the first data arrives, with the OTLP
  endpoint, the Alertmanager webhook and a config snippet for each, plus a status strip showing
  which sources are receiving. Backed by the new `GET /api/ingestion/status`. Installs that
  already have analysis history see no change apart from the status strip.
- Added an Integrations page (`/integrations`) listing every data source (OTLP, Alertmanager,
  Prometheus, CSV) with its endpoint, a config snippet, whether data is arriving, and the most
  recent received alerts. Received alerts can now be read back with `GET /api/alerts` (filters:
  `status`, `service`, `finding_id`, `since`, `limit`; API token required like every read).
  Findings and cases linked to an alert show an "Alert: <name>" badge. Alerts from the last 24h are
  shown as a timeline - one lane per alert rule, a bar per firing (solid while firing, faded once
  resolved), severity colors with labels, and a marker where an alert was linked to a finding -
  under a firing / linked / resolved summary and above a list grouped by rule ("5× in 24h", expand
  for each occurrence). The Overview shows the summary and timeline once any alert has arrived.
- The Integrations page and the first-run panel can **Send test alert** (a synthetic alert through
  the real receive, enrich and Slack path, via `POST /api/integrations/alertmanager/test`, which
  needs the API token) and **Load demo data** (a bundled checkout series analyzed through the
  normal CSV endpoint). `/findings?finding=<id>` opens that finding directly, and alerts linked to a
  finding without a case link there. The Settings page's OTLP card moved to Integrations.
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
