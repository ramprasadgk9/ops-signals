# Grafana Plugin: Sign-in, Roles and Who Did What

How people sign in to Ops Signals through the Grafana plugin, what each Grafana role can do, how the
plugin records who did what, and how to check it all on your own machine.

## In short

- **Nobody signs in to Ops Signals.** People use the plugin as the Grafana user they already are.
- **Their Grafana role decides what they can change.** Viewer, Editor and Admin, set in Grafana as
  usual (or by the company login system that feeds Grafana).
- **Names are recorded** on what people do: "Answered Expected change by priya", "Created by
  admin", "Resolved by sam", "Owner sam · last edited by priya".
- **This is the Grafana plugin.** The standalone web UI signs in through your company's sign-in
  proxy instead (see [Plugin or web UI?](#plugin-or-web-ui)).

## How it works

The plugin's Configuration page has a **Connect through** choice:

| Choice | How requests go | Sign-in and roles |
| --- | --- | --- |
| **Grafana** (recommended) | Browser → Grafana → Ops Signals backend | Yes. Grafana adds the API token and says who the user is. |
| **Browser, directly** (development) | Browser → Ops Signals backend | No. Everyone can do everything, no names are recorded. |

Through Grafana, Grafana's plugin proxy calls the backend at the Backend URL. It adds the API token
from the plugin's encrypted settings (so the token never reaches a browser) and an
`X-Grafana-Context` header with the signed-in user and their role, which a browser can't change.
The backend reads it in `backend/app/identity.py` and applies the roles in `backend/app/roles.py`.

## Who can do what

| Action | Viewer | Editor | Admin |
| --- | :-: | :-: | :-: |
| See Overview, findings, cases, schedules, alerts, memory | ✓ | ✓ | ✓ |
| Ask Ops Signals, rate its answers | ✓ | ✓ | ✓ |
| Preview an autonomous metric plan (nothing is saved) | ✓ | ✓ | ✓ |
| Answer "Was this real?" (it changes the trust numbers for everyone) | – | ✓ | ✓ |
| Create a case; investigate, add the root cause, resolve, publish to memory | – | ✓ | ✓ |
| Create or sync a ticket from a case | – | ✓ | ✓ |
| Run Analysis (Interactive), Run once (Autonomous) | – | ✓ | ✓ |
| Save, edit, pause or delete a schedule | – | ✓ | ✓ |
| Configuration page, test alerts, analyzer and behavior labs, case imports, test-data reset | – | – | ✓ |

What a Viewer sees: the locked buttons stay visible with a 🔒 and the reason underneath, for example
"Editors can run analyses. Ask your Grafana admin for the Editor role." The case drawer is
read-only, with a note saying so.

The backend enforces the same table, so a hand-made request is refused too: it gets a 403 with the
same reason, and nothing changes.

## Who did what

| Where | What it shows |
| --- | --- |
| Under "Was this real?" | "Answered Expected change by priya · 10m ago" (one answer per finding: the latest replaces the one before) |
| Under a case button, and in the case drawer | "Created by admin · 3h ago", "Resolved by sam" |
| On the schedule card | "Owner sam · last edited by priya · 1d ago" |
| Web UI case page | "… by admin" next to Created and Resolved |

Only what was done in the plugin through Grafana, or in the web UI with sign-in on, has a name.
Older records, and anything done without sign-in or in "Browser, directly" mode, show no name;
nothing is guessed.

## Set it up (Grafana admin, once)

1. Install the plugin and restart Grafana (it reads the plugin's proxy route only when it starts).
2. Go to **Administration → Plugins and data → Plugins → Ops Signals → Configuration**.
3. Choose **Connect through: Grafana**.
4. Enter the **Backend URL as the Grafana server reaches it**, for example
   `http://ops-signals-backend:8000`. With Grafana in a container and the backend on the same
   computer, use `http://host.docker.internal:<port>`, not `localhost`.
5. If the backend sets `OPS_SIGNALS_API_TOKEN`, enter it in **API token**. Grafana stores it
   encrypted and never sends it to a browser.
6. Click **Save settings**, then check the **Setup check** below: the Backend row should say
   "Reached through Grafana · you are admin (Admin)".
7. Give people roles in Grafana (**Administration → Users and access → Users**), or let the company
   login system assign them.

Set `OPS_SIGNALS_API_TOKEN` on the backend for real use. Without it, anyone who can reach the
backend directly (not through Grafana) isn't limited by roles. See
[`security-model.md`](security-model.md#roles).

To set it up with provisioning, see the plugin's [`README`](../frontend/README.md#configure).

## Plugin or web UI?

| | Grafana plugin (`localhost:3000` locally) | Web UI (`localhost:5174` locally) |
| --- | --- | --- |
| Sign-in | Grafana's | Your company's sign-in proxy, when set up |
| Roles | Viewer / Editor / Admin, from Grafana | Viewer / Editor / Admin, from company groups |
| Records who did what | Yes | Yes, with sign-in on |

Without a sign-in proxy the web UI has no roles: everyone can do everything. Setting it up is in
[`web-ui-sign-in.md`](web-ui-sign-in.md).

## Check it on your machine

The local stack (`scripts/run_grafana_stack.sh` and `docker compose up -d grafana`) already connects
the plugin through Grafana: `grafana/provisioning/plugins` sets the Backend URL to
`http://host.docker.internal:8002` at every Grafana start. The local Grafana's anonymous visitor is
an **Editor**, so everything works without signing in.

Before you start: open http://localhost:3000, open the browser's DevTools, tick **Disable cache**
and reload, so the browser loads the current plugin.

### 1. Without signing in (your everyday local setup)

Open http://localhost:3000/a/breezypoppy3596-opssignals-app/ops-signals in a private window.

- The chips at the top say `anonymous · Editor`, then Backend, Metrics and Case memory.
- The footer of Interactive Analysis says "Backend: through Grafana (set by your Grafana admin)".
- Nothing is locked.

### 2. As a Viewer

Create a Viewer: as admin, **Administration → Users and access → Users → New user** (new users are
Viewers). The plugin's end-to-end tests create one too: `ops-signals-test-viewer`, password
`viewer-test-password`. Sign in as the Viewer in a private window and open **More apps → Ops
Signals**.

| Where | What you should see |
| --- | --- |
| Top chips | `<user> · Viewer` |
| Interactive Analysis | 🔒 Run Analysis, with "Editors can run analyses. Ask your Grafana admin for the Editor role." |
| Autonomous Analysis → Configure | 🔒 Edit and 🔒 Pause on the schedule card, with "Editors can change schedules." |
| Autonomous preview | Preview metric plan works; 🔒 Run autonomous analysis once, with the reason |
| A finding (Autonomous → Overview) | "Was this real?" locked with the reason; 🔒 Create case; Open case #N still opens the case, read-only, with 🔒 Save Case |
| Memory & Alerts → Ask Ops Signals | Works |

To check that the backend refuses it too, not only the buttons, run this in the browser console
while signed in as the Viewer:

```js
fetch('/api/plugin-proxy/breezypoppy3596-opssignals-app/backend/api/findings/0/feedback', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{"verdict":"real_problem"}'}).then(r => r.json()).then(console.log)
```

It answers `{"detail": "Editors answer \"Was this real?\" … Ask your Grafana admin for the Editor
role."}`.

### 3. As admin

Sign in as `admin` / `admin`.

- The chip says `admin · Admin`, and nothing is locked.
- The Configuration page's Setup check says "Reached through Grafana · you are admin (Admin)".
- Answer "Was this real?" on a finding, or resolve a case in the drawer: "Answered … by admin" and
  "Resolved by admin" appear, in the plugin and on the web UI's case page. (This changes your local
  data.)

### Automated checks

```bash
cd frontend
NODE_PATH=./node_modules npx playwright test --project=plugin
```

`smoke/through-grafana.spec.ts` checks the anonymous visitor and the admin's name through Grafana;
`smoke/viewer-role.spec.ts` signs in as the test Viewer and checks the locked button and the
backend's 403. The backend's rules are in `tests/api_backend/test_grafana_roles.py` and
`tests/api_backend/test_actor_identity.py`.

## Troubleshooting

| You see | Why | Fix |
| --- | --- | --- |
| Chip says `anonymous · Viewer` and everything is locked locally | Grafana runs with an older `docker-compose.yml` | `docker compose up -d grafana` |
| No name chip, and a backend picker behind "change" | The plugin is in "Browser, directly" mode | Choose **Connect through: Grafana** on the Configuration page |
| Setup check: "Grafana can't reach http://localhost:…" | Inside Grafana's container, `localhost` is the container | Use `host.docker.internal` or the backend's service name. On Linux, start the backend with `--host 0.0.0.0`. |
| Setup check: "Grafana has no proxy route for Ops Signals yet" | Grafana started before the plugin was updated | Restart Grafana |
| Settings you saved went back to the local defaults | Provisioning re-applies them at every Grafana start | Expected locally; change `grafana/provisioning/plugins` instead |
| Buttons look unlocked, or old text | The browser kept the previous plugin | DevTools → Disable cache, reload |
| A 403 "Editors can …" in a script or an old tab | The request came through Grafana as a Viewer | Use an Editor (or Admin) account |
