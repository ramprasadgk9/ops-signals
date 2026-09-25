# Security model

Ops Signals is built to run **inside a trusted network**, next to your Prometheus and Grafana. It
is not hardened to face the internet. Read this page before you run it anywhere other people can
reach.

## What's open by default

With no configuration, **the API has no authentication**. Anyone who can reach the backend (port
`8000`, or the web UI's `/api/` proxy on `8080`) can read every finding, case and stored metric,
start analyses, and change cases and autonomous policies.

Two kinds of endpoint are riskier than the rest, so they're **off by default**:

| Switch | Default | What it enables |
| --- | --- | --- |
| `OPS_SIGNALS_ENABLE_TESTING_API` | `false` | `POST /api/testing/reset-operational-data`, which deletes all runs, findings, cases and vector memory. When it's off, the route doesn't exist (404). |
| `OPS_SIGNALS_ALLOW_FILE_WRITES` | `false` | Endpoints that write or delete files on the backend's filesystem: saving and deleting analyzers (`/api/admin/analyzers`), promoting a draft, generating adapter code and deleting analyzers in the Analyzer Lab, and saving behavior definitions to a pack file. When it's off they return 403, and the rest of the labs still work (drafts, validation, dry runs, routing tests). |

The local dev scripts (`scripts/run_all.sh`, `scripts/run_grafana_stack.sh`) turn both on. The
one-command demo turns on file writes only, and those land inside a throwaway container.

## Turning on authentication

Set one shared token:

```bash
export OPS_SIGNALS_API_TOKEN="$(openssl rand -hex 32)"
```

After that, every request needs `Authorization: Bearer <token>`, except:

- `GET /api/health`, so load balancers and container health checks still work.
- The receivers: `POST /api/integrations/alertmanager`, `POST /api/alerts` and `POST /api/events`.
  Each one checks its own token (`OPS_SIGNALS_ALERT_RECEIVER_TOKEN` or `OPS_SIGNALS_EVENTS_TOKEN`)
  if you set one. Otherwise it uses the API token, so setting only `OPS_SIGNALS_API_TOKEN` never
  leaves a receiver open. See [alert-enrichment.md](alert-enrichment.md).

The token also covers `GET /api/metrics`. If Prometheus scrapes the backend, give the scrape job the
token (`authorization: { credentials: <token> }`).

### Clients

| Client | How it sends the token |
| --- | --- |
| **Web UI** (`ops-signals-web` image) | Set `OPS_SIGNALS_API_TOKEN` on the web container too. Its nginx adds the header to every `/api/` request on the server side, so the token never reaches the browser. |
| **Grafana plugin** | Enter it in the **API token** field next to the backend selector. It's saved in that browser's local storage, so anyone who uses Grafana in that browser can read it. |
| **Alertmanager / CI** | `authorization: { credentials: <token> }` in the Alertmanager receiver, or `-H "Authorization: Bearer <token>"` in the deploy step. |
| **Scripts and curl** | `-H "Authorization: Bearer <token>"`. |

The web UI run by the Vite dev server (`npm run dev`) doesn't send a token, so use it against a
backend without one.

### Where to set it

- **Docker Compose (packaged):** `docker-compose.packaged.yml` passes `OPS_SIGNALS_API_TOKEN`,
  `OPS_SIGNALS_ALLOW_FILE_WRITES` and `OPS_SIGNALS_ENABLE_TESTING_API` through from your shell or
  `.env`, to both the backend and the web container.
- **Helm:** create a Secret and point `security.apiTokenSecret.name` at it. Both the backend and the
  web pods read it from there. `security.allowFileWrites`, `security.enableTestingApi` and
  `security.corsOrigins` are in `values.yaml`.

  ```bash
  kubectl create secret generic ops-signals-api-token --from-literal=api-token="$(openssl rand -hex 32)"
  helm install ops-signals helm/ops-signals --set security.apiTokenSecret.name=ops-signals-api-token
  ```

## CORS

Browsers may call the API directly only from the origins in `OPS_SIGNALS_CORS_ORIGINS` (a
comma-separated list). The default covers the local dev ports (`localhost` and `127.0.0.1` on
`3000`, `5173` and `5174`). If the Grafana plugin runs on another host, add your Grafana URL, for
example `OPS_SIGNALS_CORS_ORIGINS=https://grafana.example.com`. The web UI doesn't need an entry,
because nginx serves it from the same origin as `/api/`.

## Known limitations

- **One shared token, with no users or roles.** Anyone with the token can do everything the API
  allows, including the file writes and the reset when those are on.
- **In the Grafana plugin, the token sits in the browser.** A proper fix would route plugin
  requests through Grafana's server-side plugin proxy. That isn't built yet.
- **No TLS in the backend.** Put it behind a TLS-terminating proxy or ingress if traffic leaves
  the host.
- **The dev `docker-compose.yml` uses default passwords** for Postgres and Grafana and publishes
  their ports. Don't use it outside your own machine.

Found a vulnerability? See [SECURITY.md](../SECURITY.md).
