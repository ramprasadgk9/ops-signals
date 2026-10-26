# Changelog

Changes to the Ops Signals Grafana plugin. The plugin has its own version (1.0.x). Each Ops Signals
release names the plugin version it ships. The full project changelog is
[CHANGELOG.md](https://github.com/ramprasadgk9/ops-signals/blob/main/CHANGELOG.md).

## 1.0.35 - Unreleased (ships with the next Ops Signals release)

- **Header chips for every role.** The Backend, Metrics and Case memory chips and the setup reminder
  read the Setup check summary (`/api/setup/summary`), which every Grafana role may see; the full
  check with its details is for Grafana admins, on the Configuration page. Against an older backend
  without the summary, the plugin uses the full check as before.

- **Found automatically.** On the Alerts page, a deploy Ops Signals found in Prometheus (a new
  version on a `*_build_info` metric or a new Kubernetes ReplicaSet) carries a "Found automatically"
  tag under What changed; hovering it says how it was found. Deploys sent by CI don't get the tag.
- **Findings in plain words.** The analysis result, the investigation panel, the "Needs attention"
  rows and the finding lookup show a finding's badge (Worse, Better, Monitoring gap...) and plain
  headline, then what changed, why it matters and what to check, with the stored text under
  "Technical details". A needs-attention row no longer shows an improvement in red. Hovering
  "Happened with" explains how the other finding was picked. The buttons that switch between a
  run's findings use the plain headline too.
- **Service context.** For a service described in the wording file, findings show its importance
  ("Critical service") next to the badge, a "Your target" line and a "This service" line.
- **Why each analyzer ran.** The run's analyzer list shows each analyzer that ran with its reason
  ("Router pick", "Covers spikes", "Runs on every series") and whether it fed the finding, not the
  router's reason for a different decision. "How the router scored this series" folds the rest, with
  analyzers that aren't built in listed apart. Admins see how to install a missing library
  (Prophet). The assistant's "Why did STUMPY run?" now answers from the run's own record: it no
  longer says PyOD or ADTK ran when Z-Score did, or that only "recommended" analyzers run. The
  "Selection mode" rows are gone. An ⓘ next to each analyzer's name says what it looks for.
  Opened, "Run details" takes the full width below the Samples / Signals / Findings tiles instead
  of squeezing into the strip beside them; it reads as a link ("Run details" / "Hide run details")
  and has a "Hide run details" button at its end. The Evidence card reads "2 signal windows support this
  finding" on one line (it was split as "2 / signal / windows" beside the rest), and "1 signal
  window supports" for one.
- **Roles.** Through Grafana, a Viewer's Run Analysis, "Was this real?", Create case, case drawer
  Save, ticket, Run once and schedule buttons are locked, each with the reason ("Editors can run
  analyses. Ask your Grafana admin for the Editor role."). The case drawer is read-only for Viewers
  and shows who created and resolved the case. Clear DB for testing is for Admins.
- **Connect through Grafana.** The Configuration page chooses how the plugin reaches the backend:
  **Grafana** (recommended; new installs start here), where Grafana's plugin proxy calls the backend
  with the API token from the plugin's encrypted settings and says who the user is, or **Browser,
  directly** (as before; existing installs stay on it until switched). Through Grafana there is no
  backend picker or token field in the app, the footer says "Backend: through Grafana", and a chip
  shows who you are (`priya · Editor`). Restart Grafana after updating: it reads the new proxy route
  only at start.
- **Who did it.** Under "Was this real?": "Answered Expected change by priya · 10m ago". Under a
  case button: "Created by admin · 3h ago". On the schedule card: "Owner sam · last edited by priya ·
  1d ago". Only for what was done through Grafana; older records show no name.
- **Fixed: Autonomous Configure flashed the empty form before the saved schedule's card.** It now
  says "Loading your schedule…" until it knows.
- **Setup check on the Configuration page.** Below the Backend URL, it tests the backend, its
  database, each metrics connection and memory search, and says how to fix anything that isn't green,
  with a Test button per connection and Copy report. An unreachable backend shows as a failed check
  with the CORS and token hints. The API token can now be entered on this page too. While something
  needed is broken, the app shows a reminder that links here.
- **Honest status chips in the app header.** Backend, Metrics and Case memory come from the Setup
  check (hover for details) instead of always showing green.
- **Autonomous Configure in four steps: Data, Scope, Watch, When.** It reads from the backend's
  connection (with its clusters); the Grafana data source picker is gone, since autonomous runs
  never used it, and Preview no longer waits for it. Services and namespaces are "All" or picked
  chips; the label names, metrics-per-run limit, backend and token sit behind "change". Categories
  sit four to a row. "Once, now" or "Every 30m" replaces the Mode dropdown, and "Max parallel jobs"
  (which did nothing yet) is gone. Editing a schedule shows a banner with Cancel edit, the save
  button says what it does (Save & schedule, Save schedule, Save without schedule), and a disabled
  Preview says what is missing.
- **Interactive Analysis form in three steps: Data, What, When.** "Read metrics from" is one
  choice (Grafana data source, or an Ops Signals connection with its cluster). Service and Metric are
  the only boxes in step 2; the service label is a "change" link under Service, and Metric / PromQL
  is a switch. Time presets plus "Custom…", which applies as you change it. The backend and API
  token moved behind "change" at the bottom. A disabled Run Analysis says what is missing.
- **Fixed: Autonomous Overview failed with "could not be loaded"** once the backend held many
  analysis runs. The plugin now asks for the newest runs only.
- **New plugin id: `breezypoppy3596-opssignals-app`** (was `breezypoppy3596-ops-signals-app`).
  Grafana's catalog allows one word between the org and the type. The app's address is now
  `/a/breezypoppy3596-opssignals-app/ops-signals`. If you installed the old id: remove its folder from
  Grafana's plugins folder, install the new zip, update `allow_loading_unsigned_plugins` and any
  provisioning file, and set the Backend URL again. Settings don't carry over.
- **Configuration page with a Backend URL.** A Grafana admin sets the Ops Signals backend's address
  once (Administration → Plugins → Ops Signals → Configuration, or `jsonData.backendUrl` in
  provisioning). The app uses it by default and lists it first in the backend picker. Before this,
  the picker offered only local development addresses.
- Catalog details: current screenshots, links, minimum Grafana version (13.1), and a README for people
  installing the plugin.
- The plugin zip ships the plugin only (no web UI walkthrough videos, 12 MB → 1.3 MB), with its
  source map, LICENSE and CHANGELOG, in one folder named after the plugin id.

## 1.0.34 - 2026-10-18 (Ops Signals 0.5.0)

- Findings and their trust numbers follow 0.5.0's detection fixes: spikes at the end of the window,
  stricter single Z-Score readings, and correlation only for signals that happen close together.
- Errors name the dependency that is down (Qdrant or the database).

## 1.0.33 - 2026-10-15 (Ops Signals 0.4.0)

- **Mimir tenants and clusters**, as in the web UI: the cluster and connection on findings, symptom
  rows per cluster, cluster chips on the overview, a connection picker and Clusters section in
  Autonomous Configure, and **Query through: Ops Signals connection** in Interactive Analysis.
- Fixed: previewing a saved schedule used the default connection instead of the schedule's own.
- Findings say where their data came from (Prometheus, OTLP or CSV).
- Finding trust (how often findings like this one were real), behavior cases, **Same fix
  elsewhere**, the **Memory & Alerts** tab and symptom triage.

## 1.0.32 - 2026-10-07 (Ops Signals 0.3.0)

- **Seen before?** on the interactive result and in the case workflow.
- Jira tickets from cases, when ticketing is turned on in the backend.
- Fixed: cases in Recent Cases from History did nothing when clicked.
- The schedule card's **Remove** is now **Pause**, which is what it always did.

## Earlier

Versions before 1.0.32 shipped with Ops Signals 0.1.0 and 0.2.0: interactive and autonomous
analysis, the case workflow (finding → investigation → root cause → resolution), operational memory
and Ask Ops Signals.
