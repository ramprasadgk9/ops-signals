# Adoption Roadmap: Login, Teams and Onboarding

What Ops Signals needs so a company with many teams can adopt it with little integration work. The
rule throughout: **use what the company already has** (its login system, Grafana's roles, standard
protocols) through configuration, and never build per-vendor integrations.

## Where it stands

- **Setup check (done).** The web UI's Setup check page and the Grafana plugin's Configuration page
  test each part of an install and say how to fix anything that isn't working
  ([`ui-tour.md`](ui-tour.md#setup-check-and-settings), `GET /api/setup/check`).
- **Login:** one shared API token, `OPS_SIGNALS_API_TOKEN`, or none. There are no users or roles:
  anyone with the token can do everything ([`security-model.md`](security-model.md)).
- **Grafana plugin:** calls the backend from the browser, so the token is kept in browser storage.
- **"Who did it":** cases have a `resolved_by` field, but nothing fills it with the real user.

## Next steps

Do these in order. Each one is useful without the ones after it.

### 1. The plugin signs in through Grafana

Plugin requests go through Grafana's server-side plugin proxy instead of straight from the browser.

- The API token stays on the Grafana server, never in a browser. This fixes the known limitation in
  [`security-model.md`](security-model.md).
- The backend learns who is asking (name and Grafana role) from the proxy.
- Cases, feedback and schedules record who did what. The UI shows it, for example "Resolved by
  Priya · 2h ago", and a schedule card shows its owner and who last edited it.
- The plugin's API token field goes away.

**Size:** medium. It touches how the plugin calls the backend (a plugin backend or Grafana's route
proxy) and adds a "who" field to a few records. Mockup first.

### 2. Roles: Viewer, Editor, Admin

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
