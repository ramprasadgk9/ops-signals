# Web UI: Sign-in Through Your Company's Sign-in Proxy

How people sign in to the standalone web UI, how their company groups become Viewer, Editor or
Admin, and how to try it on your own machine. For the Grafana plugin, see
[`grafana-plugin-access-and-roles.md`](grafana-plugin-access-and-roles.md).

## In short

- **Ops Signals has no login page of its own.** Your company's sign-in proxy (any proxy or ingress
  that signs people in and passes the user on in a header) sits in front of the web UI. People sign
  in there, as they do for your other internal tools.
- **Their groups decide what they can change.** You name the groups that mean Admin and Editor;
  everyone else who signs in is a Viewer.
- **The same roles as in the Grafana plugin**, enforced by the backend on every request.
- **Names are recorded** on what people do in the web UI: "Created by priya", "Resolved by sam".
- **It's off by default.** With no sign-in set up the web UI works as before: nobody is signed in
  and everyone can change everything.

## How it works

```
Browser → company sign-in proxy → web UI (nginx) → Ops Signals backend
            signs the person in,     adds the API token,
            adds X-Forwarded-Email   drops any Grafana
            and X-Forwarded-Groups   identity headers
```

1. The sign-in proxy signs the person in and adds two headers to every request: the user (default
   `X-Forwarded-Email`) and their groups (default `X-Forwarded-Groups`, comma- or
   semicolon-separated).
2. The web UI's nginx passes those on to the backend with the API token added. It removes any
   `X-Grafana-Context` a browser sends, so nobody can pose as a Grafana user through the web UI.
3. The backend reads the user and groups (`backend/app/identity.py`) and applies the roles
   (`backend/app/roles.py`). The headers are believed only when `OPS_SIGNALS_API_TOKEN` is set,
   because only the web UI's nginx (and Grafana) hold the token.

## Who can do what

| Action | Viewer | Editor | Admin |
| --- | :-: | :-: | :-: |
| See Overview, findings, cases, schedules, alerts, memory | ✓ | ✓ | ✓ |
| Ask Ops Signals, rate its answers | ✓ | ✓ | ✓ |
| Preview an autonomous metric plan (nothing is saved) | ✓ | ✓ | ✓ |
| Answer "Was this real?" (it changes the trust numbers for everyone) | – | ✓ | ✓ |
| Create a case; investigate, resolve, add to memory, create or sync a ticket | – | ✓ | ✓ |
| Run Analysis, Analyze and Save, Run once (Autonomous) | – | ✓ | ✓ |
| Save, edit, pause or resume a schedule | – | ✓ | ✓ |
| Analyzer labs, Add Analyzer, the behavior pattern builder, case imports, test alerts | – | – | ✓ |
| See set-up details: the full Setup check, analyzer settings, lab work, case imports | – | – | ✓ |

What people see:

- **Top right**, a chip with their name and role, for example `priya · Editor`. Clicking it shows
  the group that gave the role and how they signed in.
- **Locked buttons** stay visible with a 🔒 and the reason underneath, for example "Editors can run
  analyses. Ask your Ops Signals admin for the Editor role."
- **The menu** lists only the pages their role can open (see the next table). A section left empty,
  such as Analyzer Workbench for a Viewer, goes away.
- **A page opened by its address** that their role can't use, from a bookmark or a pasted link,
  shows "Settings is for Ops Signals admins" (or "… is for Editors") and whom to ask, with a link to
  Overview. The page itself doesn't load.
- **A case page** opened by a Viewer is read-only, with a note saying so.
- **The setup reminder** on Overview shows for everyone while something needed is broken. Admins get
  a link to Setup check; everyone else reads "Your Ops Signals admin can fix this on Setup check."
- **Import past incidents** on Recurring problems is locked for anyone but Admins.
- **Autonomous Analysis** for a Viewer shows the schedule (with its owner and who last edited it) and
  what runs found, without Edit, Pause or the set-up form.

A hand-made request is refused too: the backend answers 403 with the same reason.

## Who sees which page

| Page | Viewer | Editor | Admin |
| --- | :-: | :-: | :-: |
| Overview, Alerts, Findings, Cases, Metric Usage, Behavior Intelligence, Recurring problems, Ask Ops Signals | ✓ | ✓ | ✓ |
| Autonomous Analysis | read-only | ✓ | ✓ |
| New Analysis, Recommendations | – | ✓ | ✓ |
| Integrations, Settings, Setup check, analyzer labs, Add Analyzer | – | – | ✓ |

The list lives in `backend/app/roles.py` (`PAGES`); the web UI gets it from `GET /api/me`. A page
missing from the list is for Admins only. With no sign-in every page is open, as before.

## Set up company sign-in

1. **Start from a locked-down install:** sign-in builds on the steps in
   [`security-model.md`](security-model.md#turning-on-authentication), and doesn't work without them.
2. **Put the web UI behind your sign-in proxy**, and make sure the proxy is the **only** way to
   reach it (see [Before you go live](#before-you-go-live)).
3. **Have the proxy pass the user and groups on.** Most do with a setting; for example
   oauth2-proxy with `--set-xauthrequest` and `--pass-user-headers`, or an ingress with external
   authentication that copies the response headers to the request.
4. **Turn it on in the backend:**

| Setting | Default | What it does |
| --- | --- | --- |
| `OPS_SIGNALS_AUTH_MODE` | `none` | `proxy-headers` turns sign-in on |
| `OPS_SIGNALS_AUTH_USER_HEADER` | `X-Forwarded-Email` | The header with the signed-in user |
| `OPS_SIGNALS_AUTH_GROUPS_HEADER` | `X-Forwarded-Groups` | The header with their groups |
| `OPS_SIGNALS_AUTH_EDITOR_GROUPS` | (none) | Comma-separated groups that make someone an Editor |
| `OPS_SIGNALS_AUTH_ADMIN_GROUPS` | (none) | Comma-separated groups that make someone an Admin |

   Admin wins over Editor when someone is in both.

   - **`.env` and packaged Compose:** set them in `.env`; `docker-compose.packaged.yml` passes
     them to the backend.
   - **Helm:** `security.signIn` in `values.yaml`:

     ```bash
     helm upgrade ops-signals helm/ops-signals \
       --set security.apiTokenSecret.name=ops-signals-api-token \
       --set security.signIn.mode=proxy-headers \
       --set security.signIn.editorGroups=sre,platform \
       --set security.signIn.adminGroups=ops-signals-admins
     ```

5. **Restart the backend**, open the web UI through the proxy and check **Setup check → Login**. It
   should say "Company sign-in (proxy headers) is on · you are priya@example.com (Editor, group
   sre) through company sign-in".

## Before you go live

- **Only the sign-in proxy may reach the web UI.** Its nginx adds the API token to every request,
  so anyone who can reach the web container directly can send their own user header, or none.
  Keep the web service internal (in Kubernetes a `ClusterIP` service reached only by the proxy)
  and don't publish its port.
- **A request through the web UI with no user header isn't limited by roles.** The backend can't
  tell it from a script holding the token. Setup check → Login warns when this happens; the fix is
  the point above.
- **Scripts, CI and Alertmanager** use the API token without a user header, so they aren't limited
  by roles and record no name. Separate, revocable tokens for each of them are planned (step 3 of
  [`adoption-roadmap.md`](adoption-roadmap.md)).

## Try it on your machine

No proxy needed: `OPS_SIGNALS_DEV_USER` makes every request without a Grafana user act as one
person. It works **only without an API token**, and the backend logs a warning while it's on.

1. Add it to `.env`, with the role after a colon:

   ```bash
   OPS_SIGNALS_DEV_USER=priya@example.com:Viewer
   ```

2. Restart the backend and open the web UI (`http://localhost:5174` locally).

| Where | What you should see |
| --- | --- |
| Top right | `priya · Viewer (dev)` |
| Setup check → Login | A warning: "Pretending to be priya@example.com (Viewer) with OPS_SIGNALS_DEV_USER…" |
| New Analysis | 🔒 Run Analysis, with "Editors can run analyses. Ask your Ops Signals admin for the Editor role." |
| A finding | "Was this real?" and Create case locked |
| A case page | The read-only note; Save Investigation and Add to Memory disabled |
| Menu | No Integrations, New Analysis, Analyzer Workbench, Settings or Setup check; Autonomous Analysis without "Configure" |
| `/settings` typed in the address bar | "Settings is for Ops Signals admins", and a link to Overview |
| Autonomous Analysis | The schedule without Edit or Pause, and no set-up form |
| Behavior Intelligence | New pattern and Edit copy hidden |

Change `Viewer` to `Editor` or `Admin` and restart to see the other roles. Remove the line and
restart when you're done.

To try the real header path, set `OPS_SIGNALS_API_TOKEN` and `OPS_SIGNALS_AUTH_MODE=proxy-headers`
on the backend and send the headers yourself:

```bash
curl -s -H "Authorization: Bearer $OPS_SIGNALS_API_TOKEN" -H "X-Forwarded-Email: priya@example.com" -H "X-Forwarded-Groups: sre" http://localhost:8000/api/me
```

### Automated checks

The backend's rules are in `tests/api_backend/test_web_sign_in.py` and `test_role_pages.py` (which
also fails when a page in `AppRoutes.tsx` is missing from the list); the web UI's chip and locks in
`frontend/src/components/WebSignIn.test.tsx`, the menu and closed pages in `RoleArea.test.tsx`, and
a Viewer in the browser in `tests/scenarios/integration/web-ui/roles/viewer-pages.spec.ts`.

## Troubleshooting

| You see | Why | Fix |
| --- | --- | --- |
| Chip: "Not signed in · everyone can change things" | Sign-in isn't set up | Expected with `OPS_SIGNALS_AUTH_MODE` unset |
| Chip: "Sign-in problem · see Setup check" | `proxy-headers` is on but no token is set, or the request had no user header | Set `OPS_SIGNALS_API_TOKEN`; check the proxy passes the user on, or set `OPS_SIGNALS_AUTH_USER_HEADER` to the header it uses |
| Everyone is a Viewer | Their groups aren't in the Editor or Admin lists, or the groups header is missing | Compare the groups in the chip's details with `OPS_SIGNALS_AUTH_EDITOR_GROUPS` and `OPS_SIGNALS_AUTH_ADMIN_GROUPS` |
| `OPS_SIGNALS_DEV_USER` does nothing | An API token is set | Expected: the dev user only works without a token |
| A user header your proxy sends never arrives | nginx drops headers with underscores in their names | Use a header name with dashes |
