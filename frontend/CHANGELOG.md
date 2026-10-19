# Changelog

Changes to the Ops Signals Grafana plugin. The plugin has its own version (1.0.x). Each Ops Signals
release names the plugin version it ships. The full project changelog is
[CHANGELOG.md](https://github.com/ramprasadgk9/ops-signals/blob/main/CHANGELOG.md).

## 1.0.35 - Unreleased (ships with the next Ops Signals release)

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
