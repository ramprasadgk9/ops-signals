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
| `OPS_SIGNALS_ALLOW_FILE_WRITES` | `false` | Endpoints that write or delete files on the backend's filesystem: saving and deleting analyzers (`/api/admin/analyzers`), promoting a draft, generating adapter code and deleting analyzers in the Analyzer Lab, saving behavior definitions to a pack file, and saving golden questions from Ask Ops Signals' Docs check page (`POST /api/assistant/docs-check/tests`). When it's off they return 403, and the rest of the labs still work (drafts, validation, dry runs, routing tests). |

The local dev scripts (`scripts/run_all.sh`, `scripts/run_grafana_stack.sh`) turn both on. The
one-command demo turns on file writes only, and those land inside a throwaway container.

## Turning on authentication

Set one shared token:

```bash
export OPS_SIGNALS_API_TOKEN="$(openssl rand -hex 32)"
```

After that, every request needs `Authorization: Bearer <token>`, except:

- `GET /api/health` (readiness: 503 when the database is unreachable) and `GET /api/health/live`
  (liveness: the process is up), so load balancers and container health checks still work.
- The receivers: `POST /api/integrations/alertmanager`, `POST /api/alerts` and `POST /api/events`.
  Each one checks its own token (`OPS_SIGNALS_ALERT_RECEIVER_TOKEN` or `OPS_SIGNALS_EVENTS_TOKEN`)
  if you set one. Otherwise it uses the API token, so setting only `OPS_SIGNALS_API_TOKEN` never
  leaves a receiver open. See [alert-enrichment.md](alert-enrichment.md).
- External ticketing webhooks: `POST /api/integrations/ticketing/{provider}/webhook`.
  External SaaS providers (e.g. Jira Cloud) cannot provide internal Ops Signals Bearer tokens.
  Instead, incoming webhook requests are authenticated cryptographically via HMAC-SHA256 signature
  verification (`X-Hub-Signature` or `X-Atlassian-Webhook-Signature`) using the configured provider secret
  (e.g., `OPS_SIGNALS_JIRA_WEBHOOK_SECRET`). Requests failing signature verification are rejected with HTTP 401,
  and so is every webhook while no secret is configured: without one there is nothing to verify.

With a token set, the interactive API docs (`/docs`, `/redoc`) and the OpenAPI schema
(`/openapi.json`) are switched off. FastAPI serves them outside the token check, and a browser
can't send the token to them. Without a token they stay available as before.

Unexpected server errors (HTTP 500) don't include internal details such as driver messages or
database hosts. The response gives a short error id, and the details are in the backend log under
that id.

The token also covers `GET /api/metrics`. If Prometheus scrapes the backend, give the scrape job the
token (`authorization: { credentials: <token> }`).

### Clients

| Client | How it sends the token |
| --- | --- |
| **Web UI** (`ops-signals-web` image) | Set `OPS_SIGNALS_API_TOKEN` on the web container too. Its nginx adds the header to every `/api/` request on the server side, so the token never reaches the browser. |
| **Grafana plugin, through Grafana** (recommended) | A Grafana admin enters it once on the plugin's Configuration page. Grafana stores it encrypted and adds it to the requests its plugin proxy sends to the backend, so it never reaches a browser. |
| **Grafana plugin, browser directly** | Each person enters it in the **API token** field next to the backend selector. It's saved in that browser's local storage, so anyone who uses Grafana in that browser can read it. |
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
`3000`, `5173` and `5174`). If the Grafana plugin calls the backend from the browser ("Browser,
directly") and Grafana runs on another host, add your Grafana URL, for example
`OPS_SIGNALS_CORS_ORIGINS=https://grafana.example.com`. Neither the plugin connected through
Grafana nor the web UI needs an entry: Grafana's server calls the backend, and nginx serves the web
UI from the same origin as `/api/`.

## Roles

When the plugin connects through Grafana, each request is limited by the person's Grafana role in
the organization (`backend/app/roles.py`):

| Role | May |
| --- | --- |
| **Viewer** | Read everything except set-up details, ask Ops Signals and rate its answers, preview an autonomous plan, test a connection |
| **Editor** | Also answer "Was this real?", create and work on cases (investigation, root cause, resolution, memory, tickets), run analyses, save, change, pause or delete schedules |
| **Admin** | Also the plugin's Configuration page, test alerts, the analyzer and behavior labs, case imports, and the test-data reset; and reading set-up details: the full Setup check (addresses, which secrets are set, fixes), analyzer settings, lab work and case imports. Everyone else gets each check's name and status from `GET /api/setup/summary` |

Setup, the plugin-or-web-UI question and step-by-step checks are in
[`grafana-plugin-access-and-roles.md`](grafana-plugin-access-and-roles.md). A refused request gets a 403 saying why ("Editors can change schedules. Ask your Grafana admin for
the Editor role."), and the plugin shows the same reason under the locked button. Grafana sets the
role on every request and a browser can't change it, so with `OPS_SIGNALS_API_TOKEN` set (only
Grafana can reach the backend) roles can't be bypassed. Without a token, someone who calls the
backend directly isn't limited by roles at all.

The web UI gets the same roles from your company's groups ([`web-ui-sign-in.md`](web-ui-sign-in.md)):

- **Company sign-in** (`OPS_SIGNALS_AUTH_MODE=oidc`): the backend signs people in with your identity
  provider over OpenID Connect and checks the provider's signed ID token itself. Who signed in lives
  in a signed, `HttpOnly` session cookie. The web UI's nginx no longer adds the API token, so a browser
  has only its session's rights; a change carried by the cookie must come from the web UI's own
  address; and `X-Grafana-Context` counts only on requests that carry the API token. The API token is
  required in this mode, and scripts keep using it.
- **Sign-in proxy** (`OPS_SIGNALS_AUTH_MODE=proxy-headers`): the backend believes the proxy's user
  header only with `OPS_SIGNALS_API_TOKEN` set, and only the web UI's nginx holds the token, so the
  web container must be reachable only through the proxy.

## Who did what

When the plugin connects through Grafana, Grafana's plugin proxy adds `X-Grafana-Context` to each
request: the signed-in Grafana user and their role. The backend records that name on what the
person does (a "Was this real?" answer, a case they open, a schedule they create or change) and the
UI shows it, for example "Created by priya · 3h ago", "Resolved by sam". Grafana replaces any copy of that header a
browser sends.

A request made straight to the backend can carry a made-up header, so the names are only as
trustworthy as the backend's own access control. With `OPS_SIGNALS_API_TOKEN` set, only Grafana
(which holds the token) and other token holders can call it at all. Without a token, treat the names
as a convenience, not an audit trail. The web UI with sign-in on records the signed-in person's
name the same way. Other requests (the web UI without sign-in, scripts, the plugin in "Browser,
directly" mode) record no name.

## Known limitations

- **Roles only for signed-in people.** Requests through the plugin's Grafana proxy, or through the
  web UI behind a sign-in proxy, are limited by the person's role. Anything else with the token -
  the web UI without sign-in, scripts, the plugin in "Browser, directly" mode - can do everything
  the API allows, including the file writes and the reset when those are on. One shared token for
  everything; separate tokens per integration are planned ([`adoption-roadmap.md`](adoption-roadmap.md)).
- **In the Grafana plugin's "Browser, directly" mode, the token sits in the browser.** Connect the
  plugin through Grafana to keep it on the Grafana server.
- **The web UI knows who is using it only behind a sign-in proxy.** Without one, its actions
  record no name.
- **No TLS in the backend.** Put it behind a TLS-terminating proxy or ingress if traffic leaves
  the host.
- **The dev `docker-compose.yml` uses default passwords** for Postgres and Grafana and publishes
  their ports. Don't use it outside your own machine.

Found a vulnerability? See [SECURITY.md](../SECURITY.md).
