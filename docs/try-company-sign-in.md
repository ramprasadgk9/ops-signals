# Try Company Sign-in

Check that the web UI's company sign-in and its roles work with a real identity provider before you
onboard a team. Steps 1 to 5 set up a provider and point Ops Signals at it; step 6 checks what each
role sees; step 7 cleans up. How it works and how to set it up for real is in
[`web-ui-sign-in.md`](web-ui-sign-in.md).

Do steps 1 to 5 one of two ways:

| | Option 1: the script | Option 2: by hand |
| --- | --- | --- |
| Good for | A quick check you can repeat | Learning the steps, or trying the provider you'll really use |
| Provider | A throwaway Keycloak (open source) in Docker | Keycloak in Docker, or any OpenID Connect provider you can register apps in |
| Time | About 5 minutes (the first run downloads Keycloak, about 500 MB) | About 20 minutes |

## Before you start

- `./scripts/setup.sh` has run once, and Docker is running (not needed for Option 2 with your own
  provider).
- `./scripts/run_all.sh` is stopped (Ctrl+C).
- Your `.env` sets no sign-in lines: `OPS_SIGNALS_AUTH_MODE`, `OPS_SIGNALS_OIDC_*`,
  `OPS_SIGNALS_AUTH_ADMIN_GROUPS`, `OPS_SIGNALS_AUTH_EDITOR_GROUPS`, `OPS_SIGNALS_PUBLIC_URL`,
  `OPS_SIGNALS_TEST_SIGN_IN` or `OPS_SIGNALS_DEV_USER`. Put `#` in front of any you have while you try
  this; `run_all.sh` loads `.env` last, so they would win. The script checks this for you.

The settings for this test go in `tmp/keycloak/keycloak.env` (git ignores `tmp/`), never in `.env`,
so the Grafana stack and your usual setup are not touched.

## Option 1: the script does steps 1 to 5

```bash
./scripts/try_keycloak_sign_in.sh up
```

It starts Keycloak on `127.0.0.1:8180` (step 1), creates the realm `acme` with three groups and three
users (step 2), registers Ops Signals as a web app (step 3), adds the groups claim with Keycloak's
default "Full group path" on (step 4), writes the settings and starts `run_all.sh` with them (step
5). Then go to [step 6](#6-check-it).

| Command | What it does |
| --- | --- |
| `./scripts/try_keycloak_sign_in.sh up` | Steps 1 to 5 and starts the app. Running it again starts the realm from scratch |
| `./scripts/try_keycloak_sign_in.sh up --no-start` | Steps 1 to 5 without starting the app |
| `./scripts/try_keycloak_sign_in.sh start` | Starts the app again with the same settings |
| `./scripts/try_keycloak_sign_in.sh path-off` | Keycloak sends group names (`ops-signals-admins`): roles work |
| `./scripts/try_keycloak_sign_in.sh path-on` | Keycloak sends group paths (`/ops-signals-admins`): everyone is a Viewer |
| `./scripts/try_keycloak_sign_in.sh down` | Removes Keycloak and the settings file |

Ports in use elsewhere: set `KEYCLOAK_PORT` (8180) or `FRONTEND_PORT` (5174) before `up`.

## Option 2: steps 1 to 5 by hand

Each step says what to do in Keycloak, then what it means in any other provider.

### 1. Start a provider

```bash
docker run -d --name keycloak-try -p 127.0.0.1:8180:8080 -e KC_BOOTSTRAP_ADMIN_USERNAME=admin -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin quay.io/keycloak/keycloak:26.0.7 start-dev
```

Wait about 30 seconds, open http://localhost:8180 and sign in as `admin` / `admin`.

**Another provider:** use a test tenant or a free developer account of the provider you'll really use.
You need rights to register apps and manage groups there.

### 2. Create groups and users

1. Realm menu (top left) → **Create realm** → name `acme` → Create.
2. **Groups** → Create group: `ops-signals-admins`, `ops-signals-editors`, `support`.
3. **Users** → Add user, once per row below. Turn **Email verified** on, fill in a first name, **Join
   groups** → the group → Create. Then on the user's **Credentials** tab → **Set password**, with
   **Temporary** off.

| Username | Email | Group | Password | Role in Ops Signals |
| --- | --- | --- | --- | --- |
| `john` | `john@acme.example` | `ops-signals-admins` | `Passw0rd-john` | Admin |
| `elena` | `elena@acme.example` | `ops-signals-editors` | `Passw0rd-elena` | Editor |
| `vic` | `vic@acme.example` | `support` | `Passw0rd-vic` | Viewer |

The `@acme.example` addresses are made up on purpose and never emailed.

**Another provider:** create (or pick) three test people in three groups like these.

### 3. Register Ops Signals as a web app

1. **Clients** → **Create client** → OpenID Connect, Client ID `ops-signals` → Next.
2. **Client authentication** on, **Standard flow** on → Next.
3. **Valid redirect URIs** `http://localhost:5174/api/auth/callback`; **Valid post logout redirect
   URIs** `http://localhost:5174/signed-out` → Save.
4. **Credentials** tab → copy the **Client secret**.

**Another provider:** in its admin console create a web (OpenID Connect) app with the same two
addresses, then note its client ID, client secret and issuer address.

### 4. Add the groups claim

1. **Clients** → `ops-signals` → **Client scopes** tab → `ops-signals-dedicated`.
2. **Configure a new mapper** (or Add mapper → By configuration) → **Group Membership**.
3. Name `groups`, **Token Claim Name** `groups`, **Add to ID token** on. Leave **Full group path**
   on for now, to see the trap in step 6 → Save.

**Another provider:** on the app, add a groups claim to the ID token; look for Token configuration,
Claims, Claim mappers or Groups claim. If it can't be named `groups`, note its name for step 5.

### 5. Point Ops Signals at it and start

Make an API token (company sign-in needs one):

```bash
openssl rand -hex 32
```

Create `tmp/keycloak/keycloak.env` with your token and client secret:

```bash
OPS_SIGNALS_API_TOKEN=<the token>
OPS_SIGNALS_AUTH_MODE=oidc
OPS_SIGNALS_OIDC_ISSUER_URL=http://127.0.0.1:8180/realms/acme
OPS_SIGNALS_OIDC_CLIENT_ID=ops-signals
OPS_SIGNALS_OIDC_CLIENT_SECRET=<the client secret>
OPS_SIGNALS_AUTH_ADMIN_GROUPS=ops-signals-admins
OPS_SIGNALS_AUTH_EDITOR_GROUPS=ops-signals-editors
OPS_SIGNALS_OIDC_PROVIDER_NAME="Acme login"
OPS_SIGNALS_PUBLIC_URL=http://localhost:5174
```

Then start the app with it:

```bash
set -a; source tmp/keycloak/keycloak.env; set +a; ./scripts/run_all.sh
```

- Keep `127.0.0.1` in the issuer: Keycloak names itself by the address it is reached on, so the
  backend and the browser must use the same one.
- Keep the quotes around a value with a space (`"Acme login"`): without them the shell runs the second
  word as a command and the terminal hangs at a `login:` prompt.
- `OPS_SIGNALS_PUBLIC_URL` is needed locally because the dev server hides the real address from the
  backend.

**Another provider:** use its issuer address (it must start with `https://`), its client ID and
secret, your group names in the two lists, and `OPS_SIGNALS_OIDC_GROUPS_CLAIM=<name>` if the claim
isn't called `groups`.

## 6. Check it

Open http://localhost:5174. Option 2 with another provider: use your own test people in place of
john, elena and vic.

| # | Do | You should see |
| --- | --- | --- |
| 1 | Open the web UI | "Sign in with Acme login" |
| 2 | Sign in as `john` / `Passw0rd-john` | The provider's login page, then back in Ops Signals as **john · Viewer** |
| 3 | Open the name chip (top right) | "Groups your provider sent: `/ops-signals-admins`". With "Full group path" on the group doesn't match the list, so john is only a Viewer |
| 4 | Turn the path off: Option 1 `./scripts/try_keycloak_sign_in.sh path-off` in another terminal; Option 2 the mapper → **Full group path** off → Save. Then chip → **Sign out** | Keycloak asks "Do you want to log out?", then "You're signed out of Ops Signals" |
| 5 | Sign in as `john` again | **john · Admin**; the chip shows `ops-signals-admins` |
| 6 | Setup check → Login | "Company sign-in is on · you are john@acme.example (Admin, group ops-signals-admins) …"; **Test sign-in** says Ops Signals can reach your provider |
| 7 | Sign out, sign in as `elena` / `Passw0rd-elena` | **Editor**: New Analysis shown; Settings and Setup check hidden |
| 8 | Sign out, sign in as `vic` / `Passw0rd-vic` | **Viewer**: Autonomous Analysis read-only; `/settings` says it's for admins |

## 7. Clean up

| Option 1 | Option 2 |
| --- | --- |
| Ctrl+C, then `./scripts/try_keycloak_sign_in.sh down` | Ctrl+C, then `docker rm -f keycloak-try`, and delete `tmp/keycloak/keycloak.env` |

Then start `./scripts/run_all.sh` as usual: with no sign-in set, nobody signs in and everything is
open, as before.

## If something doesn't match

| You see | Why | Fix |
| --- | --- | --- |
| The terminal stops at `login:` | A value with a space in `keycloak.env` has no quotes | Ctrl+D (or close the tab), quote the value, start again |
| The script says your `.env` sets sign-in settings | Those lines would override the test's | Put `#` in front of them while you test |
| "Sign-in isn't set up yet" | A line is missing from `keycloak.env` | The sign-in page names it |
| The provider says the redirect address is wrong | It differs from `http://localhost:5174/api/auth/callback` | Fix it in the provider; keep `OPS_SIGNALS_PUBLIC_URL` |
| Everyone is a Viewer | The groups that arrive don't match the lists | Compare the chip's "Groups your provider sent" with the two lists |
| Port 8180 or 5174 is in use | Something else runs there | Option 1: `KEYCLOAK_PORT=8280 ./scripts/try_keycloak_sign_in.sh up`; Option 2: another `-p` port in step 1 and the issuer |

## No Docker? Test accounts

To see only Ops Signals' own screens, without a real provider: add `OPS_SIGNALS_TEST_SIGN_IN=true` to
`.env` and restart `./scripts/run_all.sh`. It starts a small built-in test provider on `127.0.0.1:9400`
with accounts sam (Viewer), priya (Editor), ada (Admin) and lee (no groups), each one click, no
password. Setup check → Login warns while it's on; remove the line and restart to turn it off.
