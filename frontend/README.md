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

1. In Grafana, go to **Administration → Plugins and data → Plugins → Ops Signals → Configuration**.
2. Enter the **Backend URL**: the Ops Signals backend's address as your users' browsers reach it,
   for example `https://ops-signals.example.internal`. Then click **Enable and save**.
3. On the backend, allow this Grafana to call it from the browser: add Grafana's address to
   `OPS_SIGNALS_CORS_ORIGINS`, for example `OPS_SIGNALS_CORS_ORIGINS=https://grafana.example.com`.
4. If the backend requires an API token (`OPS_SIGNALS_API_TOKEN`), enter it in the app's
   **API token** field. It's kept in that browser only.

To set it up with provisioning instead, put this in Grafana's `provisioning/plugins` folder:

```yaml
apiVersion: 1

apps:
  - type: breezypoppy3596-opssignals-app
    org_id: 1
    disabled: false
    jsonData:
      backendUrl: https://ops-signals.example.internal
```

## Use

Open **Apps → Ops Signals**. Choose **Interactive Analysis** to analyze one metric now, or
**Autonomous Analysis** to set up scheduled analysis. The backend picker lists the configured backend first, followed by the
local development addresses.

### How the data flows

The plugin reads metrics through Grafana's own Prometheus datasource, using the signed-in user's
permissions. It sends the samples and the query details (service, metric, time range, no credentials)
from the browser to the Ops Signals backend, which runs the analysis and stores findings and cases in
its own database. If the backend has a Prometheus connection of its own, you can also choose
**Query through: Ops Signals connection** and the backend queries Prometheus directly.

## Troubleshooting

- **"App not found"**: the plugin isn't loaded. Check Grafana's log for an unsigned-plugin message
  and the `allow_loading_unsigned_plugins` setting above.
- **Nothing loads and the browser console shows a CORS error**: Grafana's address is missing from
  the backend's `OPS_SIGNALS_CORS_ORIGINS`.
- **401 errors**: the backend requires an API token; enter it in the **API token** field.
- **The backend picker doesn't show your backend**: save a Backend URL on the Configuration page.

## Links

- [Feature walkthrough](https://github.com/ramprasadgk9/ops-signals/blob/main/docs/grafana-plugin-feature-walkthrough.md)
- [Security model](https://github.com/ramprasadgk9/ops-signals/blob/main/docs/security-model.md)
- [Report an issue](https://github.com/ramprasadgk9/ops-signals/issues)
- [Building and running the plugin locally](https://github.com/ramprasadgk9/ops-signals/blob/main/docs/grafana-plugin-local-setup.md)
