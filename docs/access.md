# Who Can Use Ops Signals

Out of the box, anyone who can reach Ops Signals can see and change everything. Three steps fix
that: lock the API, give people roles, check it.

The same three steps are on **Setup check → Login**, which shows the step you're on and the next
thing to do. You can follow the app or this page; the easiest route is to open Setup check, do what
its button says, click **Check again**, and repeat until the row is green. In the web UI, **Watch how
(2 min)** on that row plays all three steps, recorded on a throwaway install with a test company
login.

Where Setup check is: in the web UI, **Setup check** at the bottom of the menu; in Grafana,
**Administration → Plugins and data → Plugins → Ops Signals → Configuration**, below the settings.

> **Before you start**
>
> - Ops Signals is installed and running ([`deploy.md`](deploy.md)), and you can open the web UI or
>   the Grafana plugin.
> - You can change the backend's settings and restart it: the `.env` file for Docker Compose, or Helm
>   values.
> - For the Grafana plugin: you're a Grafana **Admin**.
> - For company login: you, or your identity team, can add an app in your company's login system.

Each step below says where it happens:

| Tag | Where |
| --- | --- |
| **[Server]** | The machine or cluster running Ops Signals: `.env`, Helm values, restarts |
| **[Grafana]** | Grafana's own menus |
| **[Company login]** | The admin console of the system behind your company's sign-in page. It's outside Ops Signals; your identity team runs it |
| **[Ops Signals]** | The web UI or the plugin |

## Step 1. Lock the API

Everyone does this; it takes a minute.

1. **[Server]** In the folder with your `.env`, make a token:

   ```bash
   echo "OPS_SIGNALS_API_TOKEN=$(openssl rand -hex 32)" >> .env
   ```

   With Helm, put it in a Secret and set `security.apiTokenSecret.name`
   ([`security-model.md`](security-model.md#where-to-set-it)).
2. **[Server]** Restart: `docker compose -f docker-compose.packaged.yml up -d`. Compose gives the
   token to the backend and to the web UI's container, which adds it for the browser.
3. **[Ops Signals]** Setup check → Login now says **API locked**. Scripts, CI and Alertmanager need
   the token from now on: [where each one puts it](security-model.md#clients).

## Step 2. Give people roles

Pick the row for how your team opens Ops Signals:

| How does your team open Ops Signals? | Go to | Takes | People then sign in with |
| --- | --- | --- | --- |
| In **Grafana** (the plugin) | [2a](#2a-grafana-plugin) | 2 min | Their Grafana account |
| In the **web UI**, with your company login (recommended for the web UI) | [2b](#2b-web-ui-with-company-login) | 15 min | Their company account |
| In the **web UI**, behind a sign-in proxy you already run | [2c](#2c-web-ui-behind-your-sign-in-proxy) | 10 min | Your proxy's sign-in |
| Only me, on my own laptop | [Step 3](#step-3-check-it) | 0 | Nobody: fine on a laptop, not on a shared network |

Both Grafana and the web UI? Do 2a and 2b: they share the token and the roles.

### 2a. Grafana plugin

1. **[Grafana]** **Administration → Plugins and data → Plugins**, search *Ops Signals*, open the
   **Configuration** tab.
2. **[Grafana]** **Connect through:** choose **Grafana**. **Backend URL:** the address Grafana's
   server uses to reach the backend, for example `http://ops-signals-backend:8000`.
3. **[Grafana]** Paste the token from step 1 into **API token** and click **Save settings**. Grafana
   stores it encrypted and never sends it to a browser.
4. **[Grafana]** Give people Viewer, Editor or Admin as usual, in **Administration → Users and
   access → Users**, or let the login system that feeds Grafana do it.

More: [`grafana-plugin-access-and-roles.md`](grafana-plugin-access-and-roles.md).

### 2b. Web UI with company login

Works with any login system that supports OpenID Connect.

1. **[Ops Signals]** Setup check → Login → **Choose how people sign in** → copy the **redirect
   address**. It looks like `https://ops.example.com/api/auth/callback`.
2. **[Company login]** Add a new **web application**. The menu is often called *Applications*, *App
   registrations* or *Clients*. Paste the redirect address. No access? Send this step to your
   identity team.
3. **[Company login]** On that app, add a **groups** claim to the ID token. Write down the **issuer
   URL**, **client ID** and **client secret**.
4. **[Server]** Add them to `.env`, with the groups that make someone an Editor or an Admin, and
   restart:

   ```bash
   OPS_SIGNALS_AUTH_MODE=oidc
   OPS_SIGNALS_OIDC_ISSUER_URL=https://login.example.com/...
   OPS_SIGNALS_OIDC_CLIENT_ID=ops-signals
   OPS_SIGNALS_OIDC_CLIENT_SECRET=...
   OPS_SIGNALS_AUTH_EDITOR_GROUPS=sre,platform
   OPS_SIGNALS_AUTH_ADMIN_GROUPS=ops-signals-admins
   ```

   Everyone else who signs in is a Viewer. Helm and every other setting:
   [`web-ui-sign-in.md`](web-ui-sign-in.md#company-sign-in-openid-connect).
5. **[Ops Signals]** Setup check → Login → **Test sign-in**, then sign in in the new tab.

Not ready for your real login system? `./scripts/try_keycloak_sign_in.sh up` starts a throwaway one
with a Viewer, an Editor and an Admin ([`try-company-sign-in.md`](try-company-sign-in.md)).

### 2c. Web UI behind your sign-in proxy

1. **[Server]** Make the proxy the **only** way to reach the web UI: don't publish the web
   container's port; in Kubernetes, use a `ClusterIP` service reached only by the proxy.
2. **[Server]** Have the proxy pass the signed-in user and their groups on in headers (by default
   `X-Forwarded-Email` and `X-Forwarded-Groups`).
3. **[Server]** Set `OPS_SIGNALS_AUTH_MODE=proxy-headers`, `OPS_SIGNALS_AUTH_EDITOR_GROUPS` and
   `OPS_SIGNALS_AUTH_ADMIN_GROUPS` in `.env`, then restart.

More: [`web-ui-sign-in.md`](web-ui-sign-in.md#sign-in-proxy-proxy-headers).

## Step 3. Check it

1. **[Ops Signals]** Open Setup check and click **Check again**. The Login row is green, with all
   three steps ticked:

   | Login row says | You are |
   | --- | --- |
   | Open: no API token is set… | Before step 1 |
   | API locked. But nobody signs in to the web UI… | After step 1: pick a web UI path in step 2 |
   | API locked. You are admin (Admin) through Grafana… | Done, for the plugin |
   | Company sign-in is on · you are priya@example.com (Editor, group sre)… | Done, for the web UI |

2. **[Ops Signals]** Sign in as a Viewer in a private window. **Run Analysis** shows a 🔒 and the
   reason ("Editors can run analyses…"). That's the proof the roles work.

Top right of the web UI, a chip shows who you are: `Not signed in · everyone can change things`
(click it for the next step), or a name and role such as `priya · Editor`.

## What each role can do

The backend checks this on every request, from the plugin and the web UI alike
(`backend/app/roles.py`). A refused request gets a 403 with the reason, and the UI shows the same
reason under a locked button.

| Action | Viewer | Editor | Admin |
| --- | :-: | :-: | :-: |
| See Overview, findings, cases, schedules, alerts, memory | ✓ | ✓ | ✓ |
| Ask Ops Signals, rate its answers | ✓ | ✓ | ✓ |
| Preview an autonomous metric plan (nothing is saved) | ✓ | ✓ | ✓ |
| Answer "Was this real?" (it changes the trust numbers for everyone) | – | ✓ | ✓ |
| Create a case; investigate, add the root cause, resolve, publish to memory, create or sync a ticket | – | ✓ | ✓ |
| Run Analysis, Analyze and Save, Run once (Autonomous) | – | ✓ | ✓ |
| Save, edit, pause, resume or delete a schedule | – | ✓ | ✓ |
| Settings and Integrations (web UI), the plugin's Configuration page | – | – | ✓ |
| Analyzer and behavior labs, Add Analyzer, case imports, test alerts, the test-data reset | – | – | ✓ |
| See set-up details: the full Setup check, analyzer settings, lab work, case imports | – | – | ✓ |

Everyone else gets each Setup check row's name and status, without the details, for the setup
reminder and the plugin's header chips. Which web UI pages each role can open is in
[`web-ui-sign-in.md`](web-ui-sign-in.md#who-sees-which-page).

Scripts, CI and Alertmanager use the API token, so roles don't limit them and their actions record
no name ([`security-model.md`](security-model.md#known-limitations)).

## More Detail

- [`security-model.md`](security-model.md): what the token covers, the receivers, CORS, the risky
  switches, and the limits.
- [`web-ui-sign-in.md`](web-ui-sign-in.md): every sign-in setting, what people see, and
  troubleshooting.
- [`grafana-plugin-access-and-roles.md`](grafana-plugin-access-and-roles.md): the plugin's connect
  modes, who did what, checking roles on your machine, and troubleshooting.
- [`try-company-sign-in.md`](try-company-sign-in.md): a throwaway Keycloak or test accounts for each
  role.
