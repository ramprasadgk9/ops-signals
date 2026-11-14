# Changelog

## 0.6.3 - 2026-11-14

Includes Grafana plugin 1.0.38.

**Findings and cases**

- **Every finding shows its number.** Cards and the details title show it (`#4182 · payments-api ·
  error_rate`). To come back to a finding later, search `#4182` on the Findings page, or click the
  number to copy a link (`/findings?finding=4182`). Both open the finding even when it is outside
  the selected time window. A case made from a finding says "From finding #4182", linked back. See
  [Finding numbers](docs/operational-findings.md#finding-numbers-coming-back-to-a-finding).
- **Seen before? says what happened last time.** Each past-case match, here and under a case's
  Similar Cases, says in one line whether it was fixed and how, the likely cause if nobody verified
  it, or what its guided investigation found. Below that line you see the case's state ("Resolved ·
  cause verified") and a link to the case. Above the list, a line says how many matches were fixed. See
  [What happened last time](docs/operational-memory.md#what-happened-last-time-each-past-case-match).

**Autonomous Monitoring**

- **Metrics a run couldn't check are counted.** A scheduled run whose metrics had too much missing
  data (more than 30% of readings) or too few readings (under 30) used to finish with no findings,
  and the page read as if everything was fine. Execution Summary now has a **Not checked** tile,
  and each run in the history says how many it couldn't check ("33 not checked: too little
  data"). When every metric is not checked, Prometheus usually wasn't collecting for part of the
  window. See [Why does a run say "Not checked"?](docs/autonomous-analysis-preview.md#why-does-a-run-say-not-checked)
  The API returns `not_checked_jobs` with a run, and `jobs_not_checked` with a stored run.
- **Open goes to the finding.** **Open** in Top findings, here and on the Overview, opens that
  finding's details instead of the Findings list.
- **Run history names how many services a run covered** ("checkout, drift-lab + 12 more").

**Analyzer Labs**

- **The STUMPY Motif Lab finds repeated shapes again.** Since 0.6.0 it ran STUMPY the way
  scheduled analysis does, looking for the most unusual stretch, so a repeated shape got no
  finding. The lab now asks for motif mode. Scheduled analysis is unchanged.

**Project**

- Two links that pointed at files outside the repo are fixed (SUPPORT.md and the assistant
  writing guide).
- The demo guide and README say to stop a running plain demo before starting it with local AI:
  the backend looks for the model only when it starts.
- Newer minimum versions of two Python dependencies: `httpx` 0.28.1 and `PyJWT` 2.15.1 (used for
  company sign-in).

## 0.6.2 - 2026-11-13

Includes Grafana plugin 1.0.37.

**Upgrading**

- **Helm: `helm install` with default values now stops until you name a database.** The chart no
  longer ships an example Postgres URL with a password as its default. Set
  `database.urlSecret.name` to a Secret holding the URL (recommended), or `database.url` for a
  quick test; with neither, the install fails with a message saying which to set. The chart doesn't
  install Postgres or Qdrant: point it at your own. See [Kubernetes: Helm](docs/deploy.md#kubernetes-helm).
- **Docker Compose: the databases listen on this machine only.** In `docker-compose.yml` every port
  is published on `127.0.0.1`, and so is Alertmanager in `docker-compose.alerting.yml`. In
  `docker-compose.packaged.yml` only the web UI (`8080`) and the API (`8000`) are open to other
  machines; Postgres and Qdrant are not. To reach the database from another machine, use an SSH
  tunnel: `ssh -L 5432:127.0.0.1:5432 your-server`.

**Findings**

- **Findings use the alert on their metric.** Findings read the alerting rules of the Prometheus
  connection they came from and add where the metric stands against the alert's line ("Back below
  the 5% alert line since ..."), the alert's description as **Why it matters**, and its runbook
  link. This works for raw metrics and recording rules; a service-specific alert wins over a
  generic one. Nothing is stored, and a finding without an alert is unchanged.
- **The details chart marks what the sentence says.** A finding's chart shades the stretch or
  marks the moment its sentence names: a stuck value or odd stretch, each burst of a spike, a grey
  **No data** stretch, and a level change and its way back. Trends and forecasts stay unmarked.
  The section is now called **What the readings show**, and the y axis keeps decimals.

**New Analysis**

- **Recording rules are marked.** New Analysis and the plugin's Interactive Analysis tag recording
  rules (such as `service:error_rate:percent`) with their group. A picked rule shows its saved
  query, how often it runs, the metrics it reads, whether its last run failed and the alerts that
  use it. Finding details add **How this was measured** for runs that read a rule
  (`GET /api/prometheus/recording-rules`).
- **Fixed: the sample CSVs failed to upload** with "CSV is missing required columns: ['metric']"
  on the default Prometheus CSV provider. A file without a metric column now takes the Metric typed
  at upload.

**Setup and project**

- **Python 3.13 is supported.** `scripts/setup.sh` and `scripts/bootstrap_sample.sh` accept it,
  and CI compiles every Python file on 3.11, 3.13 and 3.14.
- **CI checks the Helm chart** on every run.
- **Current Limitations** in the README lists a known blind spot: a metric with fewer than 30
  readings, or one that often loses scrapes, can get no finding at all
  ([#87](https://github.com/ramprasadgk9/ops-signals/issues/87)).
- Two tests that failed on slow CI runners are fixed.

## 0.6.1 - 2026-11-09

Includes Grafana plugin 1.0.36.

**Investigate a finding**

- **Investigate button.** With AI on, Needs attention cards from Prometheus and the finding's
  details have **Investigate**. It runs read-only checks against the finding's Prometheus, the
  deploys recorded for the service and past cases, then lists steps: what it checked and found,
  what you need to check yourself (with the exact query), and what a past case suggests. It says
  where to look, never "the root cause is"; you confirm the cause and fix on the case. See
  [Investigate a finding](docs/investigate.md).
- **Steer it.** The checks show up as they run; Stop any time. Mark a step **Found something** or
  **Ruled out** with a note, ask or tell it something to start the next round, or **Keep going**
  when it pauses. Each step shows the query behind it, and a step nothing backs is marked **Not
  checked**.
- **What your team knows about a service.** Before it starts, the dialog shows what the service
  depends on (with suggestions from its own labels), behaviour that is normal for it, and its
  owner, channel and runbook, editable in place and saved for everyone (`/api/service-notes`).
- **Save to a case.** Opens a case for the finding and attaches the investigation; the case's
  Investigation tab shows it, and **Use as note** puts a draft built from the steps in the note box.
- **Works with local and hosted models.** Anthropic, OpenAI-compatible APIs and Ollama use tool
  calling; a model without tool calling still investigates. Each round has a time limit
  (`OPS_SIGNALS_INVESTIGATION_ROUND_SECONDS`, default 120 s). Viewers read saved investigations but
  can't start or steer one.
- A Prometheus run now keeps the PromQL it ran (`analysis_runs.promql`, a nullable column added on
  startup), so an investigation queries the same series.

**Demo and New Analysis**

- **Things to try includes Investigate.** With AI on, the guide has an eleventh step after the pods
  step: open today's checkout-api finding and click **Investigate**. It ticks off when the
  investigation starts. With AI off the guide keeps its ten steps.
- **Sample CSVs for everyone.** New Analysis → CSV Upload shows four sample files with a
  **Download CSV** link each, the first rows of the one you pick, and which columns are needed, so
  you can see what your own file should look like (`GET /api/samples`). In the hosted and the
  local demo, **Analyze it** analyzes one in a click.
- **Fixed: Investigate in the demo with local AI.** Docker Compose reads the repo's `.env`, so the
  dev stack's Ollama settings reached the demo with no address, and the backend looked for Ollama
  inside its own container: every investigation failed. An empty or `localhost` Ollama address now
  means the `ai` profile's model, or Ollama on your machine; a model API (`DEMO_AI_URL`) always
  wins; `OPS_SIGNALS_OLLAMA_TIMEOUT_SECONDS` and `OPS_SIGNALS_INVESTIGATION_ROUND_SECONDS` now reach
  the backend; and the log says which AI is on in one line.
- **Fixed:** a link to a case's tab (the guide's **Create the case**) did nothing when that case
  was already open; it now switches to the tab.

**Findings**

- **Finished problems say so, and leave Needs attention.** When the latest analysis shows a spike,
  data gap or stuck value already ended, the card, its details and the Slack message add "Normal
  again since 09:45" (or "Data has been arriving again since…", "Changing again since…"). One hour
  after it ended, a problem that needed attention moves to Context only with the **Over** badge,
  on the Findings page, the Overview count, the shift handoff, the `ops_signals_active_findings`
  metric and the Grafana plugin. Nothing is deleted; a case on it stays open.
- **Level changes that came back say so.** After each run, Ops Signals checks whether an open level
  change's level came back near where it was before the jump (80% of it undone for 15 minutes).
  The card reads "Latency rose sharply for 4 hours, then came back … Back to about 200 ms since
  11:30" and moves to Context only an hour later; a level only partly back says "Partly back: about
  700 ms since 11:30" and stays. Before, the card kept saying "stayed higher" after a recovery.
  Trends aren't covered yet (#82).
- **Fixed: clear level changes scored too low (#76).** A level change was scored against the whole
  series' spread, which includes the jump itself, so a clear change halfway through could score
  well under its real size. It is now scored against the noise on each side of the jump.

## 0.6.0 - 2026-11-02

Includes Grafana plugin 1.0.35.

**Install and run**

- **Production-ready Helm chart.** Settings for Jira, Slack, Alertmanager, AI and Qdrant secrets,
  `extraEnv` / `extraEnvFrom`, readiness and liveness probes on `/api/health` and
  `/api/health/live`, resource requests and limits, a service account, Ingress TLS, and the web UI's
  proxy pointed at the release's own backend service. The MCP server is optional (off by default)
  and now has its own image, `ghcr.io/ramprasadgk9/ops-signals-mcp`.
- **A demo you can try in one command, with a guided tour.** `docker-compose.demo.yml` starts with
  "Things to try", ten steps from a finding to a published fix (`OPS_SIGNALS_DEMO_TOUR=false` hides
  it). AI is off, local (`--profile ai` runs Ollama with gemma3:4b) or from a model API you set in
  `demo/ai-api.env` (`DEMO_AI_URL`, `DEMO_AI_KEY`, `DEMO_AI_MODEL`, or the Anthropic settings).
  Demo mode (`OPS_SIGNALS_DEMO_MODE`) keeps a shared demo safe: visitors can't reach Admin pages,
  schedules, deletes, Jira or ingestion, and AI answers can be replayed from recorded ones. Two of
  the demo's changes now come from specific pods, and the demo starts with the same history each
  time.
- **Who can use Ops Signals, in three steps.** `docs/access.md` is the one place for locking the
  API, giving people roles (through the Grafana plugin, a company login or a sign-in proxy) and
  checking it, with the only roles table. Setup check → Login says which step you're on and the
  one next action.
- **Fixed: the demo's guide stuck on step 4 without AI.** Its case step only ticked off with Draft
  from case, which shows only with AI on, so the no-AI demo never got past it. With AI off the step
  is now "Make a case" and ticks off when a case is created.
- **Fixed: signing out of a company login asked "Do you want to log out?"** Sign-out now passes the
  sign-in's ID token to the provider, so it ends the session straight away.
- **Fixed: setup script.** The Qdrant readiness check works, and Python 3.11 installs a matching
  numpy.

**Analysis**

- **Metrics split by pod are analyzed instead of refused.** New Analysis stopped with "matched N
  series, which differ by pod", which is most Kubernetes metrics. It now combines the pods the way
  scheduled runs read that metric (highest, added up, average or lowest, from
  `config/prometheus_metric_knowledge.yaml`), analyzes the one line, and says which pod the change
  came from. Preview shows the split and the odd pod out; the Pods box picks another way to combine
  or one pod. Works past 20 pods (labels only, up to 2,000 series). Pod labels are recognised as
  `pod`, `pod_name`, `kubernetes_pod_name`, `instance` or `host` by default.
- **Per-service analyzer settings.** Files in `config/analyzer_overrides.d/` change an analyzer's
  settings, or which analyzers run, for one service or metric (exact or wildcard), each with a
  reason. Only settings an analyzer lists as tunable can change, and a file with a problem is
  skipped and reported while the others apply. Findings made with them say so ("Found with custom
  settings", the value used and the default) and their trust drops the tested rate ("Custom
  settings · not tested"). Setup check lists what's in use, skipped files and overrides that
  matched nothing. Overrides now merge key by key, so changing one setting keeps the rest of its
  block.
- **Settings in use.** Analyzer Workbench → Settings in use shows what every run uses: each setting
  with its value, the file it comes from and what it means; what's changed from the defaults;
  which analyzers run; and, for a picked service and metric, which override won. Keys no analyzer
  reads are flagged as likely typos. Analyzer Labs say they are a sandbox.
- **"Which analyzer fits my metric?"** replaces the Recommendations form: pick an analyzed metric
  and see Good fit, Can help and Not a fit, with what each analyzer looks for and whether it ran on
  that metric last time. Fit score and confidence move into a "How sure?" tooltip.
- **Multi-metric patterns match in scheduled and OTLP analysis.** Those analyze each metric in its
  own run, so a pattern over two metrics (pool exhaustion, cascading failure) never matched there.
  Rules are now checked again across a cycle's runs, per service.
- **Fixed: custom metrics shared one analysis job.** An explicit metric list or include pattern ran
  one metric per service and skipped the rest; each now gets its own job.
- **Fixed: one huge metric could hide a whole service.** Series discovery downloaded every series
  and trimmed afterwards; at about a million series Mimir refused the answer. Each request now asks
  for only as many series as it keeps.
- **Fixed: backends sharing a database could repeat work.** A scheduled analysis is claimed by one
  backend before it runs, and the OTLP analysis cycle runs on one backend at a time. See
  `docs/running-multiple-backends.md`.
- **Stored points: each saved once, and deleted after 30 days.** A schedule used to save its whole
  window on every run (48 copies of each point a day for a 24h window every 30 minutes); a run now
  saves only new points. Points older than `OPS_SIGNALS_POINT_RETENTION_DAYS` (30; 0 keeps all) are
  deleted about once an hour. Findings are never deleted, points behind a case are kept, and a
  finding whose chart data is gone says why.

**Findings, cases and memory**

- **The Overview leads with what needs you now.** "Look at this first" names the one problem to open;
  Needs Attention lists this shift's open cases, combined patterns and new problems; the shift
  handoff is a button.
- **"Fix didn't hold."** A finding or case back within 30 days of a fix on the same service says so
  on the finding, the new case and the old case, naming the old fix and what it left open. Found
  without AI; with AI on, "Why might it not have held?" lists up to three possible reasons, never
  saved. Also in the Grafana plugin.
- **Draft from case.** With AI on, Editors can draft Root Cause and Resolution from the case's notes,
  ticket comments, matched deploy and similar past cases. Drafts are never saved by themselves, can
  be undone, and drop any sentence that names a number, version or name not in the case, claims
  certainty, or claims a fix the case never mentions.
- **Case timeline and write-up.** Publish Knowledge shows the case's timeline (built without AI) and
  time to fix, and a write-up saved with the case and added to memory. With AI on, Draft write-up
  fills it in through the same checks.
- **AI wording for unfamiliar metrics.** With AI on, a finding on a metric Ops Signals has no
  description for can get a plain-language explanation. `docs/ai-features.md` lists every place AI
  is used, what each sends and what shows without it.
- **Finding cards: Seen before.** The card's right column shows the closest past case and what fixed
  it, or "New pattern"; "Recurring · N past cases" opens the details there. Trust for findings
  without a service label counts answers per metric and shows "2 of 5 answers" until the team's own
  rate takes over.
- **Filter by service.** Findings and Cases have a Service dropdown with counts (`?service=`); the
  plugin's Autonomous overview has one too. `GET /api/cases?service=` filters before the limit.
- **Behavior Intelligence filter and pattern search.** Findings can show only those that are part of
  a combined pattern (`?only=patterns`), and search finds a pattern's findings by its name or rule
  id.
- **Cases and Investigations are one page.** Cases has Open / In progress / On hold / Resolved / All
  tabs; `/investigations` opens the In progress tab.
- **Behavior rules in plain words.** Conditions are picked as [metric] [is rising / is falling / has
  an unusual spike / changed by more than N%], and See it on my data tries a draft rule on a
  service's recent runs before saving.
- **Metric Usage: Add to Grafana and Drop.** Metrics nobody watches get a ready query for Grafana or
  copyable scrape config to drop them, with checkboxes for several at once, and recording rules
  nobody reads get removal steps. Storage leads with series counts and shows cost only when a rate
  is set.
- **Runbook link in Slack alerts.** An alert rule's `runbook_url` shows as "Runbook: Open the
  runbook" in the enriched message.
- **What's what?** Findings, Cases, Behavior Intelligence and Recurring problems explain their words
  and the signal → finding → case → memory chain, with `docs/glossary.md` behind them.
- **Fixed: past-case search ranked on the wrong vector.** Memory points left behind by deleted cases
  forced every symptom search onto the full-document vector. They are removed at startup, only when
  the database holds cases.
- **Fixed: case drafts failed on cases opened from a finding.** The technical title is replaced by
  the finding's plain headline before drafting.

**Project**

- **Contributor and community files.** `CONTRIBUTING.md` with DCO sign-off, a dev container, Code of
  Conduct (Contributor Covenant 2.1), `SUPPORT.md`, `GOVERNANCE.md`, `MAINTAINERS.md` and
  `CITATION.cff`. `docs/glossary.md`, `docs/vision.md`, and a guide to writing docs Ask Ops Signals
  can answer from.
- **CI runs on demand.** CI, Demo smoke test and Integration start from Actions → Run workflow; image
  and plugin builds still run on release tags.

**Earlier in this release**

- **Company sign-in for the web UI.** With `OPS_SIGNALS_AUTH_MODE=oidc` Ops Signals signs people in
  itself with any OpenID Connect provider: a sign-in page, the provider's page, and back with the
  role their groups give (`OPS_SIGNALS_AUTH_ADMIN_GROUPS` / `_EDITOR_GROUPS`). The backend checks the
  provider's signed ID token itself (PKCE, state, nonce; RS/PS/ES keys only) and keeps who signed in
  in a signed `HttpOnly` session cookie for `OPS_SIGNALS_SESSION_HOURS` (8). The chip menu shows when
  the session ends and has Sign out; a session that ends mid-work offers to sign in again in a new
  tab without losing the page; failed sign-ins say why with an error id. Optional
  `OPS_SIGNALS_OIDC_ALLOWED_GROUPS`, groups and user claims, provider name, auto-redirect and
  `OPS_SIGNALS_PUBLIC_URL`. Needs `OPS_SIGNALS_API_TOKEN`; in this mode the web UI's nginx stops
  adding the token, changes carried by the cookie must come from the web UI's own address, and
  `X-Grafana-Context` counts only with the token. Setup check → Login shows the redirect address,
  Test sign-in and set-up help, and warns when the provider can't be reached or sends no groups.
  Packaged Compose, Helm (`security.signIn.oidc.*`) and `.env.example` carry the settings. New
  dependency: `PyJWT[crypto]`. See `docs/web-ui-sign-in.md`.
- **Try sign-in before onboarding.** `OPS_SIGNALS_TEST_SIGN_IN=true` makes `scripts/run_all.sh`
  start a local test provider (`backend/devtools/test_sign_in_provider.py`, 127.0.0.1 only) with
  test accounts for Viewer, Editor, Admin and one without groups, and turn on company sign-in for its
  own backend only. Setup check warns while it's on. `scripts/try_keycloak_sign_in.sh up` does the
  same against a real, throwaway Keycloak in Docker, set up with the documented steps (users john,
  elena and vic as Admin, Editor and Viewer); `path-off` / `path-on` show the group-path trap.

- **Fixed: case notes showed the wrong time** for anyone outside UTC. Notes were saved in UTC
  without saying so, and browsers read them as local time, so in New York a note looked 4–5 hours
  later than it was written. Notes are now saved with their zone, and notes saved earlier show the
  right time too (the web UI, the Grafana plugin and MCP all read them through the API).

- **The plugin's Autonomous Analysis is read-only for Grafana Viewers**, as in the web UI: the saved
  schedule and what runs found, without the Configure stage, Edit, Pause or "Enable category".

- **Set-up details are for Admins.** With roles on (the plugin through Grafana, or the web UI with
  sign-in), only Admins can read the full Setup check, the analyzer settings (`/api/admin/...`),
  analyzer lab work (`/api/analyzer-labs/...`) and case imports; others get a 403 "Only Grafana
  admins can see this." / "Only Ops Signals admins can see this." The new `GET /api/setup/summary`
  gives every role each check's name and status without details; the setup reminder and the
  plugin's header chips use it (the plugin falls back to the full check on an older backend). For
  non-Admins the web UI reminder says the admin can fix it instead of linking to Setup check, and
  Import past incidents on Recurring problems is locked. Setup check's Login row now warns when an
  API token is set but nobody signs in, since everyone using the web UI can then change everything.

- **The web UI shows each role only its pages.** With sign-in on, the menu lists only the pages a
  person's role can open: Viewers don't see Integrations, New Analysis, Recommendations, the analyzer
  labs, Settings or Setup check; Editors don't see Integrations, the labs, Settings or Setup check.
  Opening a closed page by its address says who it's for and whom to ask, and the page doesn't load.
  Viewers see Autonomous Analysis read-only: the schedule with its owner, and what runs found. The
  list is `PAGES` in `backend/app/roles.py`, sent by `GET /api/me` (`pages`, `read_only_pages`); a
  page not listed is for Admins. Without sign-in nothing changes. The `🔒 Admin` menu chips and the
  Admin-area notice are gone. The web UI schedule card now shows its owner and last editor for
  everyone. See `docs/web-ui-sign-in.md`.

- **Deploys are found in Prometheus, without CI.** Every 5 minutes Ops Signals looks at the last 6
  hours for a service reporting a new version on its `*_build_info` metric, and for new
  kube-state-metrics ReplicaSets. Found deploys are stored with CI's (`source: ops-signals:...`,
  description "Found automatically ...") and show in What changed, the After deploy chip, enriched
  alerts and the pod breakdown. One rollout seen both ways is stored once; a deploy CI already sent
  isn't stored again, and one CI sends later replaces the found one. `POST /api/events` rejects a
  `source` starting with `ops-signals:`. The Setup check's Deploy events line counts found deploys
  and says when the last look failed. Off with `OPS_SIGNALS_DEPLOY_DISCOVERY_ENABLED=false`. See
  `docs/deploy-discovery.md`. On screen, a found deploy under What changed (finding details, the
  Alerts page, the Grafana plugin's alerts) carries a **Found automatically** tag that says on hover
  how it was found, and Slack writes "deploy `1.0.1` (found automatically)". When no deploy is
  recorded for a service, the note says Ops Signals also looked in Prometheus. The alert and finding
  APIs add `source` to each matched change, and `deploy_discovery` to say whether it's on.

- **Active findings on `GET /api/metrics`.** `ops_signals_active_findings{service, metric, cluster,
  evidence, severity}` counts active findings the way the Overview page does, so an alert rule can
  page on strong evidence through your own Alertmanager routes. Capped at 500 series
  (`ops_signals_active_findings_dropped`), cached for 30 seconds, and `ops_signals_active_findings_up`
  is 0 when the database can't be read. The Overview page and the metric now share one rule for
  which findings are active. See `docs/finding-metrics.md`.

- **Operational Memory is now the Recurring problems page.** The name says when to open it: what
  keeps breaking, and is it worth a lasting fix. `/operational-memory` redirects to
  `/recurring-problems`, query string included. The four count cards and the Retry button became one
  line ("26 past cases searchable · all up to date"), naming only the counts that need attention,
  with Retry shown only then. Each group now says what to do next: a lasting fix when every
  verified cause is the same, a look at the causes when they differ, or recording or confirming a
  cause (with a link to the case) when none is. The ranking bar chart shows only as a jump list for
  four or more groups, since each card's badge already carries its count. The footer says the cases
  compared are the window's ("21 cases from the last 90 days compared"), which explains why that
  number can be below the total. Monitoring coverage is one line until a past incident is imported,
  and is left out entirely while memory is empty. The memory inventory and the alert-context preview
  are folded away; the import wizard's check link still opens the preview. Case Details shows
  **Seen before** when the case is one of a recurring problem: how often it happened, the cause found
  on another case, and a link that opens the page on that group. The Grafana plugin's Memory & Alerts
  section and case drawer show the same. `GET /api/memory/recurring-problems` takes `name=false` so
  that lookup skips the LLM naming the groups.

- **Behavior Lab, Analyzer Recommendation and Add Analyzer no longer hang on a large database.**
  Their sample list summarised every stored metric point on each page load; with tens of millions
  of points one call ran for 15 minutes or more, and a few at once used up the backend's database
  connections, so every other page hung too. The list now reads one row per analysis run (the 500
  newest), in milliseconds, and `GET /api/metric-analyzer-recommendations/metrics` no longer fills
  the per-sample statistics (`missing_ratio`, `min_value`... are empty there; the evaluate response
  still has them). Evaluating one metric reads only that metric's points. The integration suite's
  test data now records its runs like the app does, its cleanup no longer scans the points table,
  and the suggested-patterns tests act only on their own suggestion.
- **Findings in plain words.** Finding cards in the web UI and the Grafana plugin, and Slack
  messages, now lead with a badge (Worse, Better, Monitoring gap, Probably noise, Blip, Changed) and
  a headline, then what changed in the metric's own units and the reader's time zone, why it
  matters, what changed at the same moment, and what to check. The stored title and summary are
  under "Technical details" and don't change. An error rate or latency that dropped now reads
  "Better" instead of looking like an alarm. The wording is in `config/finding_templates.yaml`;
  edit it and save. The API returns it as `plain` on each finding. Spike signals also save their
  peak value. See `docs/finding-wording.md`. Hovering "Happened with" explains how the other
  finding was picked: same service, a different metric, both a step change, within 10 minutes.
  A slow trend whose two halves average within 5% of each other reads "Changed" ("The level has
  barely moved"), not Better or Worse.
- **Service context for findings.** Describe a service once in `config/finding_templates.yaml`
  (what it does, how important it is, the targets it's held to, such as an error rate below 1%), and
  its findings say so: "Your target: Above your 1% target since 10:54 PM (2 hours so far)", "This
  service: Customers pay for their orders here", and a "Critical service" label on the card and in
  Slack. Labels only: scores, priority and lists don't change. Shipped with no services, so nothing
  changes until you add one.
- **Router Decisions says why each analyzer ran.** The web UI's panel now leads with the analyzers
  that ran, each with its reason ("Router pick", "Covers spikes", "Runs on every series") and
  whether it fed the run's finding. Before, STUMPY and Data Health read "Not Recommended" while they
  ran, and ADTK, Kats and PyOD sat under "Recommended" though nothing can run them. The router's
  full scoring is folded under "How the router scored this series", with catalog-only analyzers
  listed apart. When an analyzer's library is missing (Prophet), admins see how to install it. Each
  run records the reason as `run_reason` and `in_finding` on its analyzer executions; see
  `docs/analyzer-recommendation.md#why-an-analyzer-ran-or-didnt`. In `all` mode, an analyzer the
  router rated below "recommended" that ran no longer reads "skipped". An ⓘ next to each analyzer
  says in plain words what it looks for, from the new `description` field in its registration (the
  Add Analyzer wizard has a "What it looks for" field for custom analyzers).
- **Sign-in and roles for the web UI.** Behind your company's sign-in proxy, set
  `OPS_SIGNALS_AUTH_MODE=proxy-headers` (with an API token): the backend reads the signed-in user
  and their groups from the proxy's headers, and `OPS_SIGNALS_AUTH_EDITOR_GROUPS` /
  `OPS_SIGNALS_AUTH_ADMIN_GROUPS` decide the role, with the same rules as the Grafana plugin. The
  web UI shows who is signed in (`GET /api/me`), locks buttons with the reason and marks Admin
  pages; names are recorded on what people do. The web UI's nginx now drops `X-Grafana-Context`
  sent by a browser. Setup check → Login says which sign-in is on and who you are.
  `OPS_SIGNALS_DEV_USER` tries it locally without a proxy. Settings are in `.env.example`,
  `docker-compose.packaged.yml` and Helm (`security.signIn`). See `docs/web-ui-sign-in.md`.
- **Fixed: a backend could fail to start** when another started at the same moment against the same
  database (both added the same new column); the column is now added with `IF NOT EXISTS`.
- **Roles in the Grafana plugin.** Through Grafana, each person's Grafana role decides what they can
  change: Viewers read and ask, Editors also run analyses, answer "Was this real?", work on cases and
  change schedules, Admins also manage settings, labs, imports and test data. The backend refuses
  anything else with a 403 that says why (`backend/app/roles.py`), and the plugin locks the buttons
  with the same reason. Closing a case records who did ("Resolved by sam"; new column, see
  `backend/migrations/011_case_resolved_by.sql`). The local Grafana's anonymous visitor is now an
  Editor so the dev stack works without signing in. See `docs/security-model.md#roles`.
- **Fixed: the MCP server's case tools** (create a case, update the root cause or resolution) failed
  when they called the case endpoints without the memory settings FastAPI normally injects.
- **The Grafana plugin can sign in through Grafana.** On its Configuration page, **Connect through:
  Grafana** (recommended, and the default for new installs) sends plugin requests through Grafana's
  plugin proxy: the API token stays encrypted on the Grafana server instead of in each browser, no
  CORS setup is needed, and the backend learns who each person is from Grafana. "Was this real?"
  answers, cases opened from findings and schedules now record who did it, shown as "Answered
  Expected change by priya · 10m ago", "Created by admin · 3h ago" and "Owner sam · last edited by
  priya". Existing installs keep "Browser, directly" until an admin switches. New columns are added
  at startup (`backend/migrations/010_actor_names.sql`). See `docs/security-model.md#who-did-what`.
- **Fixed: two backends starting at once against one database could deadlock**, and one exited
  ("Application startup failed"). Startup ran two `ALTER TABLE ops_operational_cases` statements on
  every start, even with nothing to change; they now run only when needed.
- **Setup check: what works, what to fix, and how.** A new page in the web UI (Setup check, where
  System was; `/system` still opens it) and on the Grafana plugin's Configuration page. It tests the
  backend, database, each metrics connection (with a fix that fits the failure: 401, 404, timeout,
  `localhost` inside a container), OpenTelemetry, memory search, login and risky switches, the first
  analysis, and the optional extras. Each row that isn't green has **How to fix**; connections have
  **Test**; **Copy report** gives a text summary without secrets. Overview (and the plugin) show a
  reminder only while something needed is broken. API: `GET /api/setup/check`.
- **Grafana plugin: Interactive Analysis form redone** as three steps (Data, What, When), with the
  set-once backend and token tucked away and Run Analysis saying what's missing. Same fields and
  analysis; see `frontend/CHANGELOG.md`.
- **Grafana plugin: Autonomous Configure redone** the same way (Data, Scope, Watch, When). Its
  Grafana data source picker is gone: autonomous runs always read through the backend's connection,
  so it never changed what was analysed, but Preview waited for it.
- **Fixed: the Grafana plugin's Autonomous Overview failed with "could not be loaded" on a
  long-running install.** The plugin downloaded every analysis run with its full JSON (1.6 GB and
  76 s on a dev database) to show the newest 7. `GET /api/analysis-runs` now takes `limit` (1-1000)
  and `service` / `metric_name`; the plugin asks for the newest 25, or the latest run for one service
  and metric. Without `limit` it still returns every run.
- **The Grafana plugin's id is now `breezypoppy3596-opssignals-app`** (was
  `breezypoppy3596-ops-signals-app`), as the Grafana catalog requires. An existing install has to be
  removed and installed again under the new id; see `frontend/CHANGELOG.md`. The `docker-compose.yml`
  stack needs `docker compose up -d grafana` to pick up the new plugin folder.
- **Grafana plugin: set the backend on a Configuration page.** A Grafana admin enters the Ops
  Signals backend's URL once (Administration → Plugins → Ops Signals → Configuration, or
  `jsonData.backendUrl` in provisioning). Before, the plugin offered only local development
  addresses. Plugin changes are in `frontend/CHANGELOG.md`.
- **Grafana plugin zip on every release tag** (`.github/workflows/plugin.yml`): one folder named
  after the plugin id, with source map, LICENSE, CHANGELOG, screenshots and a README for installing
  it. It's signed when a grafana.com access policy token is configured. The bundle no longer
  carries the web UI's walkthrough videos (12 MB → 1.3 MB).

## 0.5.0 - 2026-10-18

Includes Grafana plugin 1.0.34. A release of fixes from two pre-release QA passes; some change what
gets reported, so read **Detection** before comparing findings with 0.4.0.

**Detection**
- **A spike at the end of the window, or in a short series, now gets a spike detector.** The router
  never profiled a jump in the newest 3 points as a spike, and series under 50 points got none.
- **One Z-Score reading becomes a finding only if it beats chance for the series length** (|z| 3.13
  for 288 readings); two or more together keep |z| 3. Normal data no longer produces a finding.
- **Signals are only called related when they happen close together.** Behavior correlation now
  enforces `max_time_gap` and `minimum_overlap`; anomalies 16 hours apart were reported as a
  cascading failure.
- **Findings use only signals that passed their own rule**, for the summary, the score and the
  timing. A 9x spike had read "0.28x its normal range" from the weakest point. PyOD and Ruptures
  signals are scored by their size.
- **CSV interval is measured from the data** instead of assuming 5 minutes, so 15-minute and 1-minute
  exports keep their real spacing.
- **A forecast made by the straight-line fallback says so**, instead of being labelled Prophet.
- **Wording matches the numbers**: a 20% move between the window halves is no longer "broadly
  similar", and a problem in old data says when the data ended instead of "still happening".

**Trust numbers**
- **The tested numbers on each finding are refreshed** from a full run on this release (RCAEval
  RE1, 375 faults): Strong evidence 98% real (was 91%), Moderate evidence 67% (was 70%), spikes 60%,
  still no better than a random alert. Findings raised while nothing was wrong fell from 536 to 435.

**Web UI**
- **New Analysis can save a CSV run** ("Analyze and Save"), so its findings can become cases.
- **New Analysis starts empty** instead of with the lab service and metric; for CSV they only fill
  rows the file leaves without one.
- **Memory chat shows the past case it finds** (default threshold 0.40, a weaker match marked
  possible), and questions naming your own service or metric are answered from findings and cases.
- **The header's Help and Theme work**; controls that did nothing are gone. Icon-only buttons have
  names screen readers can read.
- **Cases tick "Knowledge published" only after a resolution**, and every outcome status is offered.

**Reliability**
- **Errors name the dependency that is down** (503 for Qdrant or the database) instead of a generic
  500, and the overall status includes memory. `/api/health` checks the database.
- **Analyses save on a database the backend created itself.** A fresh Postgres had no defaults and
  every save failed.
- **One slow request can no longer freeze the API**: blocking work is off the event loop, and
  in-process analyzers run one at a time.
- **Slack**: finding messages retry until they arrive and show their status; the first try runs in
  the background, so uploads don't wait for a slow webhook.
- **Operational memory keeps retrying when Qdrant is down at startup**, and cases created during an
  outage are indexed after it.
- **Resolved cases stop counting as open**; concurrent case creates for one finding share one case.
- **AI replies that aren't prose** (a broken JSON fragment, say) fall back to the deterministic answer.

**API and security**
- **Setting an API token turns off `/docs` and `/openapi.json`.** Error responses no longer include
  internal details.
- **Uploads reject infinite values** with their rows; a case import that isn't text warns instead of
  importing nothing; missing labels are stored as NULL, not the text `NaN`.
- **Case statuses and root-cause confidence are validated** (422 with the allowed values); a missing
  case or finding answers 404 by name; OTLP with an unsupported Content-Type answers 415.
- **CSV runs report the service and metric the data was stored under**, with a warning when it
  differs from what you entered.
- **Alerts and tickets leave out UI links when no UI address is set**; autonomous runs count excluded
  metrics apart from skipped jobs.

## 0.4.0 - 2026-10-15

Includes Grafana plugin 1.0.33.

- **Analyzers explained, with pictures.** `docs/analyzers-explained.md` describes the nine
  analyzers in plain words, each with a chart of the behavior it catches, a one-page comparison and
  when each one runs. `scripts/build_analyzer_guide.py` regenerates the charts and prints the guide
  as a PDF.
- **Feature availability by data source.** `GET /api/ingestion/status` now returns `features`:
  each feature's state (`on`, `partly`, `off`) worked out from the connected sources, with the
  sources it is missing. For example, with OTLP alone, findings, cases and memory are on, while
  autonomous analysis, pod drill-down, alert enrichment and Metric Usage are off and name
  Prometheus. The response also reports Grafana (configured, reachable; checked at most every 30s).
- **The web UI follows what your sources can run.** Alerts, Autonomous Analysis and Metric Usage
  move to a "More with Prometheus / Grafana" menu group, marked Connect, while their source isn't
  connected; a viewer can hide them there and bring them back. Opening one explains what it does,
  what it needs and links to Integrations, instead of an empty or failing page; earlier alerts or the
  last Metric Usage check stay visible below. When availability can't be read, the menu and pages
  look exactly as before.
- **Findings say where their data came from.** `source` (`prometheus`, `otlp`, `csv`) on every
  finding, and `?source=` on `/api/findings` and `/api/findings/search`. Cards say "via OTLP", the
  drawer explains why such a finding has no pod breakdown, and the Findings page filters by source
  when there is more than one.
- **Integrations show what each source unlocks**: an "Unlocks:" line on every tile, a Grafana tile
  with its status and setup steps, and a "What works with my data?" side panel. See
  docs/integrations.md "What each source turns on".
- **Behavior rule inputs accept `aliases`**, other names the same metric arrives under. The shipped
  memory and CPU rules alias the per-workload OpenTelemetry names (`container.*`, `k8s.pod.*`), so
  they fire on OTLP data. Inputs without aliases match as before.
- **Behavior Lab suggests metric names as you type**, from every metric name Ops Signals has
  stored, so a rule (or an alias) uses the name your source really sends.
- **Fixed: a stock OpenTelemetry Collector's metrics were rejected.** Its `otlphttp` exporter gzips
  by default, and the OTLP receiver answered every batch with a 400. Gzip bodies are now accepted,
  with the size limit applied after decompression; other encodings get a 415.
- **Fixed: analysis with many metrics ran Postgres out of connections.** Every analysis (each CSV
  upload, Prometheus run and OTLP metric group) opened its own connection pool and never closed it;
  an OTLP cycle over a real Collector's hundreds of metrics hit "too many clients". All analyses now
  share one pool per database.
- **Fixed: Ask Ops Signals scored below its golden floor after the README rewrite.** A section that
  only lists links to other sections (the README's Contents) is no longer indexed, as it outranked
  the sections holding the answers.

- **Mimir tenants and clusters in the Grafana plugin**, as in the web UI (see
  docs/standalone-prometheus-analysis.md "In the web UI and the Grafana plugin").
  Autonomous Configure has a **Prometheus connection** picker (one per tenant, with a test) and an
  always-shown **Clusters** section; both go into preview, run once and saved schedules. Interactive
  Analysis can **Query through an Ops Signals connection**: it asks for a cluster when the series is
  in several, tags the findings with it, and drops HA replica copies with a warning. Findings show
  their cluster on symptom rows, the finding panel and the case drawer, and the overview filters by
  cluster.
- **Fixed: switching Prometheus connection kept the previous connection's preview on screen** (web
  UI and plugin), so it read as the new connection's result. It clears now, and the preview names
  its connection.
- **Fixed: previewing a saved schedule in the plugin used the default connection** instead of the
  schedule's own.
- **Cases keep the cluster and connection** of the finding they were opened from.
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
