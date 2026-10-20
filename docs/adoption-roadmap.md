# Adoption Roadmap: Login, Teams and Onboarding

What Ops Signals needs so a company with many teams can adopt it with little integration work. The
rule throughout: **use what the company already has** (its login system, Grafana's roles, standard
protocols) through configuration, and never build per-vendor integrations.

## Where it stands

- **Setup check (done).** The web UI's Setup check page and the Grafana plugin's Configuration page
  test each part of an install and say how to fix anything that isn't working
  ([`ui-tour.md`](ui-tour.md#setup-check-and-settings), `GET /api/setup/check`).
- **The plugin signs in through Grafana (done, step 1 below).**
- **Roles in the plugin (done, step 2 below).** Viewer, Editor and Admin, from Grafana.
- **Web UI sign-in through a sign-in proxy (done, first half of step 3 below).** Roles from company
  groups ([`web-ui-sign-in.md`](web-ui-sign-in.md)). Named tokens are the other half, next; they also
  let the web UI insist on a signed-in user.
- **Login:** one shared API token, `OPS_SIGNALS_API_TOKEN`, or none. Outside the plugin through
  Grafana and the web UI behind a sign-in proxy there are no roles: anyone with the token can do
  everything ([`security-model.md`](security-model.md)).
- **"Who did it":** recorded for what people do in the plugin through Grafana and in the web UI with
  sign-in on. Scripts and integrations record no name (step 3b).

## Next steps

Do these in order. Each one is useful without the ones after it.

### 1. The plugin signs in through Grafana (done)

Built 2026-10-19. The Configuration page's **Connect through: Grafana** sends plugin requests through
Grafana's plugin proxy (`plugin.json` route `backend/*`), which adds the API token from the plugin's
encrypted settings and `X-Grafana-Context`, the signed-in user (`backend/app/identity.py`). "Who did
it" is recorded on "Was this real?" answers, cases opened from findings, and schedules (owner, last
editor). "Browser, directly" stays for development and for installs set up before.

What was planned:

Plugin requests go through Grafana's server-side plugin proxy instead of straight from the browser.

- The API token stays on the Grafana server, never in a browser. This fixes the known limitation in
  [`security-model.md`](security-model.md).
- The backend learns who is asking (name and Grafana role) from the proxy.
- Cases, feedback and schedules record who did what. The UI shows it, for example "Resolved by
  Priya · 2h ago", and a schedule card shows its owner and who last edited it.
- The plugin's API token field goes away.

**Size:** medium. It touches how the plugin calls the backend (a plugin backend or Grafana's route
proxy) and adds a "who" field to a few records. Mockup first.

### 2. Roles: Viewer, Editor, Admin (done)

Built 2026-10-19 for the plugin through Grafana: the table, setup and local checks are in
[`grafana-plugin-access-and-roles.md`](grafana-plugin-access-and-roles.md). The backend enforces it on every request
(`backend/app/roles.py`), and the plugin locks the buttons with the reason. Closing a case now also
records who did ("Resolved by sam"). The rules are fixed for now; letting admins change them (for
example "Viewers may answer Was this real?") waits until someone asks.

What was planned:

- **Viewer:** sees findings, cases and Overview.
- **Editor:** runs analyses, resolves and confirms cases, gives feedback, edits schedules.
- **Admin:** connections, analyzers, file writes, tokens, the data reset.

In the plugin these are Grafana's own roles, so there's nothing to set up. A button someone may not
use stays visible but disabled, with the reason ("Editors can resolve cases. Ask your Grafana
admin.").

### 3. Login modes for the web UI and the API

One setting chooses how the backend learns who is asking:

| Mode | Who it suits | What the customer does |
| --- | --- | --- |
| `none` | Trying it out, the local demo (today's default) | Nothing |
| `token` | Small teams (today) | Set one secret |
| `grafana` | Teams that work mainly in the plugin | Nothing extra (step 1) |
| `proxy-headers` | Companies with a sign-in proxy or an ingress that handles login | Name the header that carries the user and groups, and which group means Admin or Editor |

The same settings in `.env`, Compose and Helm. Alertmanager, CI and scripts get **named tokens**
(one per integration, revocable, with "last used") instead of the one shared token.

### 4. Team ownership

An admin maps services to teams (for example `checkout-*` → Payments). Findings and cases show their
owner team, and Findings, Cases and Overview get a "My team" filter, on by default, with "All teams"
one click away. Everyone can still see everything.

## Later, only when users ask

- **Built-in sign-in (OIDC)** for the web UI, for companies without a sign-in proxy.
- **Audit log** (admin only): who changed schedules, connections or analyzers, and when.
- **Strict per-team separation** (multi-tenancy), where one team can't see another's data. A large
  change; only for a customer that requires it.

## Onboarding, beyond login

- **Copy-paste recipes** in the docs: Helm with an existing Prometheus, the plugin with login
  through Grafana, behind a sign-in proxy, the Alertmanager receiver, read-only first.
- **Plugin from Grafana's catalog** ([`grafana-plugin-roadmap.md`](grafana-plugin-roadmap.md)), so
  installing it is one click.
- **Safe defaults that grow:** start read-only, then opt in to schedules, file writes and ticketing.
