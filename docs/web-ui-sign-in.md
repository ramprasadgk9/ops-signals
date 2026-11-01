# Web UI: Sign-in and Roles

To let your team sign in to the web UI, follow the three steps in [`access.md`](access.md): lock the
API, pick how people sign in, check it. This page explains how sign-in works, how company groups
become Viewer, Editor or Admin, every setting, and what people see. For the Grafana plugin, see
[`grafana-plugin-access-and-roles.md`](grafana-plugin-access-and-roles.md).

## In short

- **Two ways to sign people in.** Ops Signals can sign people in itself with your company's identity
  provider over OpenID Connect ([company sign-in](#company-sign-in-openid-connect), recommended), or
  trust a [sign-in proxy](#sign-in-proxy-proxy-headers) you already run in front of internal tools.
- **Their groups decide what they can see and change.** You name the groups that mean Admin and
  Editor; everyone else who signs in is a Viewer.
- **The same roles as in the Grafana plugin**, enforced by the backend on every request.
- **Names are recorded** on what people do in the web UI: "Created by priya", "Resolved by sam".
- **Try it before onboarding a team** with [`try-company-sign-in.md`](try-company-sign-in.md): a
  throwaway Keycloak set up by one script, or test accounts for each role.
- **It's off by default.** With no sign-in set up the web UI works as before: nobody is signed in
  and everyone can change everything.

| | Company sign-in (`oidc`) | Sign-in proxy (`proxy-headers`) |
| --- | --- | --- |
| What you run | Nothing extra: Ops Signals talks to your provider | A sign-in proxy in front of the web UI |
| What you set | Issuer, client ID and secret, two group lists | Proxy headers, two group lists, network rules so only the proxy reaches the web UI |
| A made-up user header | Counts for nothing | Works if the proxy can be bypassed |
| Signing out | Sign out in the chip menu | Your proxy's sign-out |

## Who can do what

There are three roles: a **Viewer** looks and asks, an **Editor** also runs analyses and works
cases, an **Admin** also changes settings. They are the same roles as in the Grafana plugin, in one
table: [`access.md`](access.md#what-each-role-can-do).

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
| New Analysis, Recommendations, Settings in use | – | ✓ | ✓ |
| Integrations, Settings, Setup check, analyzer labs, Add Analyzer | – | – | ✓ |

The list lives in `backend/app/roles.py` (`PAGES`); the web UI gets it from `GET /api/me`. A page
missing from the list is for Admins only. With no sign-in every page is open, as before.

## Company sign-in (OpenID Connect)

Ops Signals signs people in with any identity provider that supports OpenID Connect. People see an
Ops Signals sign-in page, go to the company's sign-in page, and come straight back.

### How it works

```
Browser → web UI (nginx) → Ops Signals backend ↔ your identity provider
          passes the        signs people in, checks the provider's signed token,
          cookie on         keeps who they are in a signed session cookie
```

1. Nobody signed in sees the sign-in page. **Sign in** goes to `GET /api/auth/login`, which sends the
   browser to the provider with a one-time state, nonce and PKCE code.
2. The provider sends the browser back to `/api/auth/callback`. The backend swaps the code for an ID
   token and checks it itself: the provider's signature (RS, PS or ES keys only), issuer, audience,
   expiry and nonce (`backend/app/oidc.py`).
3. It reads the person (`email`, else `preferred_username`) and their groups, and sets a signed,
   `HttpOnly` session cookie. Nothing is stored on the server, so several backend replicas work.
4. Every request: the cookie says who this is (`backend/app/identity.py`) and the roles apply
   (`backend/app/roles.py`). The role is worked out from the current group lists each time, so a
   change to the lists applies at once; a change of someone's groups applies at their next sign-in.

The web UI's nginx stops adding the API token in this mode, so a browser has only what its session
gives it. Scripts, CI, Alertmanager and the Grafana plugin keep using the API token as before.

### Register Ops Signals with your provider

Setup check → **Login** has these steps next to it: before sign-in is on, under **Choose how people
sign in** → **How to set up company sign-in**; once it's on, with a **Test sign-in** button.

1. **In your provider's admin console, register Ops Signals as a web app**, with the redirect
   address `<your web UI address>/api/auth/callback` (Setup check → Login shows it, with a Copy
   button).
2. **On the app you just registered, add a groups claim** to the ID token, so Ops Signals gets each
   person's groups. Look for settings named Token configuration, Claims, Claim mappers or Groups
   claim.
   - Name the claim `groups`, or set `OPS_SIGNALS_OIDC_GROUPS_CLAIM` to the name your provider uses
     (for example `roles`).
   - Some providers send group IDs instead of names, or paths like `/sre`. Put exactly what arrives
     in the Admin and Editor lists: after signing in, the name chip's menu (top right) lists the
     groups your provider sent, and so does Setup check → Login for an Admin.
   - Without the claim everyone signs in as a Viewer, and Setup check warns.

   On the same page, note the client ID, a client secret and the issuer address.
3. **Set them on the backend** and restart it. Company sign-in also needs the token from
   [`security-model.md`](security-model.md#turning-on-authentication), which scripts keep using:

| Setting | Default | What it does |
| --- | --- | --- |
| `OPS_SIGNALS_AUTH_MODE` | `none` | `oidc`: people sign in with your identity provider |
| `OPS_SIGNALS_OIDC_ISSUER_URL` | (required) | The provider's issuer; Ops Signals reads `/.well-known/openid-configuration` from it. Must be `https://` |
| `OPS_SIGNALS_OIDC_CLIENT_ID` | (required) | The app's client ID |
| `OPS_SIGNALS_OIDC_CLIENT_SECRET` | (required) | The app's client secret; never logged or shown |
| `OPS_SIGNALS_AUTH_EDITOR_GROUPS` | (none) | Comma-separated groups that make someone an Editor |
| `OPS_SIGNALS_AUTH_ADMIN_GROUPS` | (none) | Comma-separated groups that make someone an Admin (Admin wins over Editor) |
| `OPS_SIGNALS_OIDC_ALLOWED_GROUPS` | (anyone who signs in) | Only these groups may sign in; others see "You can't use Ops Signals yet" |
| `OPS_SIGNALS_OIDC_GROUPS_CLAIM` | `groups` | The claim that carries the groups (for example `roles`) |
| `OPS_SIGNALS_OIDC_USER_CLAIM` | `email`, then `preferred_username` | The claim that names the person |
| `OPS_SIGNALS_OIDC_SCOPES` | `openid email profile` | Scopes to ask for |
| `OPS_SIGNALS_OIDC_PROVIDER_NAME` | `your company account` | The sign-in button says "Sign in with …" |
| `OPS_SIGNALS_OIDC_AUTO_REDIRECT` | `false` | Skip the sign-in page and go straight to the provider |
| `OPS_SIGNALS_SESSION_HOURS` | `8` | How long a sign-in lasts |
| `OPS_SIGNALS_SESSION_SECRET` | from the API token | Signs the session cookie. Changing it, or the API token when this is unset, signs everyone out |
| `OPS_SIGNALS_PUBLIC_URL` | from the request | The address people use, when a proxy in front hides it |

   - **`.env` and packaged Compose:** set them in `.env`; `docker-compose.packaged.yml` passes them
     to the backend, and the mode to the web container.
   - **Helm:** `security.signIn.mode=oidc` and `security.signIn.oidc.*`, with the client secret from
     an existing Secret:

     ```bash
     helm upgrade ops-signals helm/ops-signals \
       --set security.apiTokenSecret.name=ops-signals-api-token \
       --set security.signIn.mode=oidc \
       --set security.signIn.oidc.issuerUrl=https://your-provider/... \
       --set security.signIn.oidc.clientId=ops-signals \
       --set security.signIn.oidc.clientSecretSecret.name=ops-signals-oidc \
       --set security.signIn.editorGroups=sre,platform \
       --set security.signIn.adminGroups=ops-signals-admins
     ```

4. **Open Setup check → Login and click Test sign-in.** It checks Ops Signals can reach the provider;
   then sign in in a new tab and **Check again**: the row says "Company sign-in is on · you are
   priya@example.com (Editor, group sre)".

### What people see

| When | What they see |
| --- | --- |
| Not signed in, any page | The sign-in page; after signing in they come back to the page they opened |
| Signed in | Their name and role top right; its menu says when the session ends, and has **Sign out** |
| The session ends while working | "Your sign-in has ended": signing in again opens a new tab, so nothing typed is lost |
| Not in an allowed group | "You can't use Ops Signals yet", with an error id |
| The provider sent no groups | "Signed in, but your groups didn't come through": they carry on as a Viewer |
| Took over 10 minutes, or another browser | "That sign-in took too long" |
| The provider refused | "Your company's sign-in didn't let you in", with what the provider said and an error id |

An error id is in the backend log with the details. The page never shows the client secret, codes or
tokens.

### Security notes

- **The API token is required** in this mode, so scripts and receivers stay protected.
- **Changes need a page from this site:** a change carried by the session cookie must have an
  `Origin` (or `Referer`) of the web UI's own address, so another site can't make one for a
  signed-in person.
- **A session can't pose as a Grafana user:** `X-Grafana-Context` counts only on requests with the
  API token (Grafana's plugin proxy adds it), and the sign-in proxy's user headers count for nothing.
- **Signing out ends the provider's session too, without asking again.** The ID token from sign-in
  is kept in an `HttpOnly` cookie sent only to `/api/auth/logout`, and handed back to the provider as
  `id_token_hint`. A token too big for a cookie is left out; the provider then asks "Do you want to
  log out?" first.
- **Cutting someone off now:** remove them from `OPS_SIGNALS_OIDC_ALLOWED_GROUPS`, or rotate
  `OPS_SIGNALS_SESSION_SECRET` to sign everyone out. Otherwise a session lasts until it ends.

## Try it before onboarding a team

[`try-company-sign-in.md`](try-company-sign-in.md) walks through it end to end: a throwaway Keycloak
set up by `scripts/try_keycloak_sign_in.sh` or by hand (or the provider you'll really use), what each
role should see, and clean-up. Without Docker, `OPS_SIGNALS_TEST_SIGN_IN=true` in `.env` gives test
accounts for each role.

## Sign-in proxy (proxy-headers)

The alternative when you already run a sign-in proxy (any proxy or ingress that signs people in and
passes the user on in a header) in front of your internal tools.

### How it works

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

### Set up a sign-in proxy

1. **Start from a locked-down install:** proxy sign-in needs the API token and network rules in
   [`security-model.md`](security-model.md), and doesn't work without them.
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

### Before you go live

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

## Try roles without signing in

For a quick look at a role with no sign-in at all, `OPS_SIGNALS_DEV_USER` makes every request without a Grafana user act as one
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

Company sign-in is in `tests/api_backend/test_oidc_sign_in.py` (with the test provider through a mock
transport) and, end to end, `tests/scenarios/integration/web-ui/roles/oidc-sign-in.spec.ts` (set
`OPS_SIGNALS_OIDC_WEB_UI_URL` to a web UI using the test provider). The backend's role rules are in
`tests/api_backend/test_web_sign_in.py` and `test_role_pages.py` (which
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
| Sign-in page: "Sign-in isn't set up yet" | `oidc` is on but a setting or the API token is missing | Setup check → Login names it |
| Setup check: "can't reach your provider" | Wrong issuer address, or the backend can't reach it | Use the issuer without `/.well-known/...`; check proxies and firewalls |
| Every company sign-in is a Viewer | The provider sends no groups claim, or under another name | Add a groups claim, or set `OPS_SIGNALS_OIDC_GROUPS_CLAIM`; Setup check warns after 5 such sign-ins |
| The provider says the redirect address is wrong | The address registered differs from the one Ops Signals sends | Copy it from Setup check → Login; set `OPS_SIGNALS_PUBLIC_URL` when a proxy hides the real address |
| `run_all.sh` stops: "also sets a company provider" | `OPS_SIGNALS_TEST_SIGN_IN` and `OPS_SIGNALS_OIDC_*` are both set | Remove one of them |
