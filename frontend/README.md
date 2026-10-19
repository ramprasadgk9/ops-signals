# Ops Signals for Grafana

Ops Signals analyzes your Prometheus metrics inside Grafana. It finds the changes that matter (spikes,
level shifts, trends, unusual behavior), says in plain words what changed and how often findings like
it turned out to be real, and turns a finding into a case you can investigate, resolve and recall the
next time the same problem comes back.

- **Interactive analysis**: pick a Prometheus datasource, a service, a metric and a time range, and
  get ranked findings with the evidence behind each one.
- **Autonomous analysis**: schedule analysis for a set of services and see what needs attention.
- **Cases and operational memory**: open a case from a finding, record the root cause and fix, and
  see **Seen before?** and **Same fix elsewhere** when a similar problem shows up again.
- **Ask Ops Signals**: ask questions about findings, cases and past fixes.

The plugin is the Grafana front end of [Ops Signals](https://github.com/ramprasadgk9/ops-signals).
The analysis runs in the Ops Signals backend, which you run yourself. It's open source (MIT) and
needs no cloud service.

## Requirements

- Grafana 13.1 or later.
- A running Ops Signals backend. See the project's
  [Quick Start](https://github.com/ramprasadgk9/ops-signals#quick-start) (Docker Compose or Helm).
- A Prometheus (or Prometheus-compatible) datasource in Grafana.

## Install

Download `breezypoppy3596-opssignals-app-<version>.zip` from the project's
[releases](https://github.com/ramprasadgk9/ops-signals/releases) and install it with the Grafana CLI:

```bash
grafana cli --pluginUrl https://github.com/ramprasadgk9/ops-signals/releases/download/v<release>/breezypoppy3596-opssignals-app-<version>.zip plugins install breezypoppy3596-opssignals-app
```

Or unzip it into Grafana's plugins folder (`/var/lib/grafana/plugins` by default) and restart Grafana.

Until the plugin is signed, Grafana loads it only when it's allowed by name:

```ini
[plugins]
allow_loading_unsigned_plugins = breezypoppy3596-opssignals-app
```

or `GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS=breezypoppy3596-opssignals-app` in Grafana's
environment.

## Configure

A Grafana admin does this once; nobody else sets anything.

1. In Grafana, go to **Administration → Plugins and data → Plugins → Ops Signals → Configuration**.
2. Leave **Connect through** on **Grafana** (recommended). Grafana's server calls the backend and
   tells it who each person is, so everyone uses Ops Signals as their own Grafana user, and cases,
   answers and schedules record who did what.
3. Enter the **Backend URL** as the Grafana server reaches it, for example
   `http://ops-signals-backend:8000`. If Grafana runs in a container and the backend on the same
   computer, use `http://host.docker.internal:8000`, not `localhost`.
4. If the backend requires an API token (`OPS_SIGNALS_API_TOKEN`), enter it in **API token**. Grafana
   stores it encrypted and never sends it to a browser. Then click **Enable and save**.
5. Check the **Setup check** below the settings. It tests the backend, its database, each metrics
   connection and memory search, and says how to fix anything that isn't green. While something
   needed is broken, the app shows a reminder that links back here.

To set it up with provisioning instead, put this in Grafana's `provisioning/plugins` folder:

```yaml
apiVersion: 1

apps:
  - type: breezypoppy3596-opssignals-app
    org_id: 1
    disabled: false
    jsonData:
      backendUrl: http://ops-signals-backend:8000
      connectMode: grafana
    secureJsonData:
      apiToken: $OPS_SIGNALS_API_TOKEN
```

**Browser, directly** (development) is the other choice: each browser calls the backend at the
Backend URL, Grafana's address must be in the backend's `OPS_SIGNALS_CORS_ORIGINS`, each person
enters the API token in their own browser, and no names are recorded. Installs configured before
this choice existed keep working this way until an admin switches them.

## Use

Open **Apps → Ops Signals**. Choose **Interactive Analysis** to analyze one metric now, or
**Autonomous Analysis** to set up scheduled analysis. The chips at the top show who Ops Signals
sees you as (for example `priya · Editor`) and whether the backend, metrics and case memory work.
In "Browser, directly" mode a backend picker behind **change** lists the configured backend first,
followed by the local development addresses.

### Who can do what

Through Grafana, each person's Grafana role decides what they can change. **Viewers** read
everything and can ask Ops Signals; **Editors** also run analyses, answer "Was this real?", work on
cases and change schedules; **Admins** also manage the plugin's settings. Locked buttons stay
visible with the reason. Give people roles in Grafana as usual (or through the login system that
feeds Grafana). In "Browser, directly" mode there are no roles. The full table and how to check it
are in [Sign-in, roles and who did what](https://github.com/ramprasadgk9/ops-signals/blob/main/docs/grafana-plugin-access-and-roles.md).

### How the data flows

The plugin reads metrics through Grafana's own Prometheus datasource, using the signed-in user's
permissions. It sends the samples and the query details (service, metric, time range, no credentials)
through Grafana (or, in "Browser, directly" mode, from the browser) to the Ops Signals backend, which runs the analysis and stores findings and cases in
its own database. If the backend has a Prometheus connection of its own, you can also choose
**Read metrics from: Ops Signals connection** and the backend queries Prometheus directly.

## Troubleshooting

Start with the **Setup check** on the Configuration page: it names what's broken and how to fix it.

- **"App not found"**: the plugin isn't loaded. Check Grafana's log for an unsigned-plugin message
  and the `allow_loading_unsigned_plugins` setting above.
- **"Grafana can't reach …"** in the Setup check: the Backend URL is wrong from where Grafana runs.
  Inside a Grafana container, `localhost` is the container itself.
- **"Grafana has no proxy route for Ops Signals yet"**: restart Grafana after installing or updating
  the plugin; Grafana reads the plugin's settings file only when it starts.
- **Nothing loads and the browser console shows a CORS error** ("Browser, directly" mode only):
  Grafana's address is missing from the backend's `OPS_SIGNALS_CORS_ORIGINS`.
- **401 errors**: the backend requires an API token. Enter it on the Configuration page (through
  Grafana), or in the app's **API token** field (browser directly).
- **The backend picker doesn't show your backend** (browser directly): save a Backend URL on the
  Configuration page.

## Links

- [Feature walkthrough](https://github.com/ramprasadgk9/ops-signals/blob/main/docs/grafana-plugin-feature-walkthrough.md)
- [Security model](https://github.com/ramprasadgk9/ops-signals/blob/main/docs/security-model.md)
- [Report an issue](https://github.com/ramprasadgk9/ops-signals/issues)
- [Building and running the plugin locally](https://github.com/ramprasadgk9/ops-signals/blob/main/docs/grafana-plugin-local-setup.md)
