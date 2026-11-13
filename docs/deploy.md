# Deploy for your team

There are two ways to run Ops Signals on one machine. They are separate setups with different
addresses:

| | Try it out | Run it for your team |
|---|---|---|
| Start | `./scripts/run_all.sh` | `docker compose -f docker-compose.packaged.yml up -d` |
| What runs | backend and web UI from source | backend, web UI and MCP server as containers |
| Metrics | mock metrics it starts for you | your own Prometheus |
| Web UI | http://localhost:5174 | **http://localhost:8080** |
| API | http://localhost:8001 | http://localhost:8000 |

Both start Postgres and Qdrant on ports 5432 and 6333, so stop one before starting the other. "Try
it out" is the [README Quick Start](../README.md#quick-start); this page is the team install.

## One Server: Docker Compose

You need Docker and a Prometheus this machine can reach.

```bash
git clone https://github.com/ramprasadgk9/ops-signals.git
cd ops-signals
echo 'OPS_SIGNALS_PROMETHEUS_URL=http://host.docker.internal:9090' >> .env
docker compose -f docker-compose.packaged.yml up -d
```

- **`OPS_SIGNALS_PROMETHEUS_URL`** is your Prometheus as the backend container sees it.
  `host.docker.internal` means the machine Docker runs on, so the line above is for a Prometheus on
  this machine at port 9090. For one elsewhere, use its address, for example
  `http://prometheus.example.internal:9090`. This stack doesn't include a Prometheus of its own, so
  without this line everything starts but there are no metrics to watch, and **Test Connection**
  on **New Analysis** fails.
- **The first start builds the three images** from this checkout, which takes a few minutes.
- **Check it:** open http://localhost:8080 → **Setup check** (bottom of the sidebar). It tests the
  database, each metrics connection and memory search, and says what to fix for anything that isn't
  green. From a terminal: `curl http://localhost:8000/api/setup/check`.
- **Before others can reach it,** lock it down: a token, then sign-in and roles
  ([`access.md`](access.md)). Without a token, anyone who can reach port 8000 can use the API.
- **Only the web UI (8080) and the API (8000) are open to other machines.** Postgres (5432) and
  Qdrant (6333) answer only on this machine, so people go through the UI or API, where sign-in and
  roles apply. To reach the database from your laptop, for a backup say, use an SSH tunnel:
  `ssh -L 5432:127.0.0.1:5432 your-server`.

Stop it with `docker compose -f docker-compose.packaged.yml down`. Your data is kept; add `-v` to
delete it too. To update, `git pull`, then run the `up` command with `--build` added, so the images
are rebuilt from the new code.

**Several Mimir tenants:** list them in a connections file and add the connections overlay.
Tokens go in `prometheus-connections.env`, never in the YAML:

```bash
cp examples/prometheus-connections.yaml prometheus-connections.yaml
printf 'MIMIR_TEAM_A_TOKEN=...\nMIMIR_TEAM_B_TOKEN=...\n' > prometheus-connections.env
docker compose -f docker-compose.packaged.yml -f docker-compose.connections.yml up -d
```

## Kubernetes: Helm

```bash
kubectl create secret generic ops-signals-db \
  --from-literal=database-url='postgresql+psycopg://USER:PASSWORD@HOST:5432/ops_signals'

helm upgrade --install ops-signals ./helm/ops-signals \
  --set database.urlSecret.name=ops-signals-db \
  --set backend.env.OPS_SIGNALS_PROMETHEUS_URL=http://prometheus-server.monitoring:9090
```

**Several Mimir tenants:** put the connections file under `prometheusConnections.config` in your
values and the tokens in a Secret named by `prometheusConnections.secretName`.

Both paths, with every integration (Jira ticketing, Slack, Alertmanager, AI assistance) and value to set, are in [`release-packaging.md`](release-packaging.md). Running
more than one backend on the same database is in
[`running-multiple-backends.md`](running-multiple-backends.md).

## Add the Grafana Plugin

Once the backend runs (Docker Compose or Helm above), your team can use Ops Signals inside your own
Grafana (13.1 or later). You need a Prometheus datasource in that Grafana.

1. **Download the plugin zip** from the project's
   [Releases](https://github.com/ramprasadgk9/ops-signals/releases): each release has
   `breezypoppy3596-opssignals-app-<plugin version>.zip` and its `.sha1`. For Ops Signals 0.6.1 that
   is plugin 1.0.36:

   ```bash
   curl -fLO https://github.com/ramprasadgk9/ops-signals/releases/download/v0.6.1/breezypoppy3596-opssignals-app-1.0.36.zip
   ```

   To build it from a checkout instead (needs Node.js 20+), run
   `./scripts/release/build_grafana_plugin_artifact.sh`; it writes the zip under `dist/release/`.

2. **Install it:** unzip it into Grafana's plugins folder (`/var/lib/grafana/plugins` by default).
   The zip holds one folder named after the plugin id, as Grafana expects. Or let the Grafana CLI
   download and unzip it: `grafana cli --pluginUrl <zip URL> plugins install
   breezypoppy3596-opssignals-app`.

   ```bash
   unzip breezypoppy3596-opssignals-app-1.0.36.zip -d /var/lib/grafana/plugins
   ```

3. **Allow it, then restart Grafana.** The plugin isn't signed yet, so Grafana loads it only when
   it's named in `allow_loading_unsigned_plugins` under `[plugins]` in `grafana.ini`, or in
   `GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS=breezypoppy3596-opssignals-app` in Grafana's
   environment. Grafana reads the plugin only when it starts. The plugin's page in Grafana then
   shows an **Invalid plugin signature** notice and an **Unsigned** badge: that's expected for an
   unsigned plugin you allowed by name, and the plugin works.

4. **Connect it to the backend** (a Grafana admin, once): **Administration → Plugins and data →
   Plugins → Ops Signals → Configuration**.
   - **Connect through:** Grafana.
   - **Backend URL:** the backend as the Grafana server reaches it, for example
     `http://ops-signals.example.internal:8000`. If Grafana runs in a container on the same machine
     as the Docker Compose install, use `http://host.docker.internal:8000`, not `localhost`.
   - **API token:** the `OPS_SIGNALS_API_TOKEN` from the backend's `.env`, if you set one.
   - Click **Enable and save**.

5. **Check it:** the **Setup check** below the settings should show the backend reached through
   Grafana. Then open **Apps → Ops Signals**.

To try this on one computer, run Grafana in Docker with the plugins folder mounted:

```bash
mkdir -p ~/grafana-plugins
unzip breezypoppy3596-opssignals-app-1.0.36.zip -d ~/grafana-plugins
docker run -d --name grafana -p 3000:3000 \
  -e GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS=breezypoppy3596-opssignals-app \
  -v ~/grafana-plugins:/var/lib/grafana/plugins \
  --add-host host.docker.internal:host-gateway \
  grafana/grafana:13.1.0
```

Sign in at http://localhost:3000 as `admin` / `admin` and continue at step 4 with
`http://host.docker.internal:8000`.

Provisioning, roles and troubleshooting are in the plugin's [`README`](../frontend/README.md) and
[`grafana-plugin-access-and-roles.md`](grafana-plugin-access-and-roles.md). To develop the plugin
from source instead (`./scripts/run_grafana_stack.sh`: Grafana on `3000`, plugin backend on `8002`),
see [`grafana-plugin-local-setup.md`](grafana-plugin-local-setup.md); for a tour of the plugin, see
[`grafana-plugin-feature-walkthrough.md`](grafana-plugin-feature-walkthrough.md).
