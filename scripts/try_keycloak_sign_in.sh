#!/usr/bin/env bash
# Try the web UI's company sign-in against a real, throwaway identity provider (Keycloak, open source)
# on this computer, following the same set-up steps a company would (docs/try-company-sign-in.md).
#
#   ./scripts/try_keycloak_sign_in.sh up            Keycloak, realm, groups, users, the app, the groups
#                                                   claim and the settings, then starts run_all.sh with them
#   ./scripts/try_keycloak_sign_in.sh up --no-start the same without starting run_all.sh
#   ./scripts/try_keycloak_sign_in.sh start         start run_all.sh with the Keycloak settings again
#   ./scripts/try_keycloak_sign_in.sh path-off      Keycloak sends group names (ops-signals-admins): roles work
#   ./scripts/try_keycloak_sign_in.sh path-on       Keycloak sends group paths (/ops-signals-admins): all Viewers
#   ./scripts/try_keycloak_sign_in.sh down          remove Keycloak and the settings file
#
# Users (password Passw0rd-<name>): john = Admin, elena = Editor, vic = Viewer (group "support").
# For this computer only. The settings live in tmp/keycloak/keycloak.env (git ignores tmp/); .env and
# the Grafana stack are not touched. KEYCLOAK_PORT (8180) and FRONTEND_PORT (5174) can be changed.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HERE="$ROOT_DIR/tmp/keycloak"
ENV_FILE="$HERE/keycloak.env"
CONTAINER=ops-signals-keycloak-try
# Lines in .env that would override these settings: run_all.sh loads .env after them.
SIGN_IN_SETTINGS='OPS_SIGNALS_(AUTH_MODE|OIDC_[A-Z_]+|AUTH_ADMIN_GROUPS|AUTH_EDITOR_GROUPS|PUBLIC_URL|TEST_SIGN_IN|DEV_USER)=' 
IMAGE=quay.io/keycloak/keycloak:26.0.7
KEYCLOAK_PORT="${KEYCLOAK_PORT:-8180}"
FRONTEND_PORT="${FRONTEND_PORT:-5174}"
REALM=acme
CLIENT=ops-signals
# Keycloak names itself by the address it's reached on: the backend and the browser must both use this one.
ISSUER="http://127.0.0.1:${KEYCLOAK_PORT}/realms/${REALM}"
USERS=(john:ops-signals-admins elena:ops-signals-editors vic:support)

kc() { docker exec "$CONTAINER" /opt/keycloak/bin/kcadm.sh "$@"; }

# Admin sign-in for kc; it expires, so each command that changes Keycloak signs in first.
kc_login() { kc config credentials --server http://localhost:8080 --realm master --user admin --password admin >/dev/null; }

wait_for_keycloak() {
  echo "Waiting for Keycloak on :${KEYCLOAK_PORT}..."
  for attempt in $(seq 1 90); do
    if curl -fsS "http://127.0.0.1:${KEYCLOAK_PORT}/realms/master/.well-known/openid-configuration" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "Keycloak did not start in time; see: docker logs $CONTAINER"
  exit 1
}

client_uuid() { kc get clients -r "$REALM" -q clientId="$CLIENT" --fields id --format csv --noquotes; }

set_full_path() {
  local cid mid
  kc_login
  cid="$(client_uuid)"
  mid="$(kc get "clients/$cid/protocol-mappers/models" -r "$REALM" --fields id,name --format csv --noquotes | grep ',groups$' | cut -d, -f1)"
  kc update "clients/$cid/protocol-mappers/models/$mid" -r "$REALM" \
    -s "config={\"claim.name\":\"groups\",\"full.path\":\"$1\",\"id.token.claim\":\"true\",\"access.token.claim\":\"true\",\"userinfo.token.claim\":\"true\"}"
}

start_run_all() {
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "No $ENV_FILE yet: run '$0 up' first."
    exit 1
  fi
  local clashes
  clashes="$(grep -E "^[[:space:]]*${SIGN_IN_SETTINGS}" "$ROOT_DIR/.env" 2>/dev/null | cut -d= -f1 | tr -d ' ' | sort -u | tr '\n' ' ' || true)"
  if [[ -n "$clashes" ]]; then
    echo "Your .env sets sign-in settings that would override Keycloak's (run_all.sh loads .env last):"
    echo "  $clashes"
    echo "Comment them out (put # in front) while you try this, then run '$0 start'."
    exit 1
  fi
  echo "Starting scripts/run_all.sh with the Keycloak settings. Open http://localhost:${FRONTEND_PORT} and sign in."
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  cd "$ROOT_DIR"
  exec ./scripts/run_all.sh
}

up() {
  command -v docker >/dev/null || { echo "docker is required"; exit 1; }
  if ! "$ROOT_DIR/.venv/bin/python" -c "import jwt" 2>/dev/null; then
    echo "Installing PyJWT (company sign-in needs it)..."
    "$ROOT_DIR/.venv/bin/pip" install -q "PyJWT[crypto]>=2.8"
  fi

  # 1. Keycloak
  if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    docker start "$CONTAINER" >/dev/null
  else
    echo "Step 1: starting Keycloak ($IMAGE)..."
    docker run -d --name "$CONTAINER" -p "127.0.0.1:${KEYCLOAK_PORT}:8080" \
      -e KC_BOOTSTRAP_ADMIN_USERNAME=admin -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin "$IMAGE" start-dev >/dev/null
  fi
  wait_for_keycloak
  kc_login

  # 2. Realm, groups, users (made-up addresses: nothing is ever emailed)
  if kc get "realms/$REALM" >/dev/null 2>&1; then
    echo "Step 2: realm '$REALM' already set up, starting it again from scratch..."
    kc delete "realms/$REALM"
  fi
  echo "Step 2: realm '$REALM', groups and users..."
  kc create realms -s realm="$REALM" -s enabled=true >/dev/null
  for group in ops-signals-admins ops-signals-editors support; do
    kc create groups -r "$REALM" -s name="$group" >/dev/null
  done
  for entry in "${USERS[@]}"; do
    local name="${entry%%:*}" group="${entry##*:}" uid gid
    uid="$(kc create users -r "$REALM" -i -s username="$name" -s email="$name@acme.example" -s emailVerified=true \
      -s firstName="$name" -s lastName=Test -s enabled=true)"
    kc set-password -r "$REALM" --username "$name" --new-password "Passw0rd-$name" >/dev/null
    gid="$(kc get groups -r "$REALM" --fields id,name --format csv --noquotes | grep ",$group\$" | cut -d, -f1)"
    kc update "users/$uid/groups/$gid" -r "$REALM" -s realm="$REALM" -s userId="$uid" -s groupId="$gid" -n >/dev/null
  done

  # 3. Register Ops Signals as a web app (the set-up dialog's step 1)
  echo "Step 3: registering Ops Signals as a web app..."
  local cid secret
  cid="$(kc create clients -r "$REALM" -i -s clientId="$CLIENT" -s protocol=openid-connect -s publicClient=false -s standardFlowEnabled=true \
    -s "redirectUris=[\"http://localhost:${FRONTEND_PORT}/api/auth/callback\"]" \
    -s "attributes={\"post.logout.redirect.uris\":\"http://localhost:${FRONTEND_PORT}/signed-out\",\"pkce.code.challenge.method\":\"S256\"}")"
  secret="$(kc get "clients/$cid/client-secret" -r "$REALM" --fields value --format csv --noquotes)"

  # 4. Groups claim (step 2), with Keycloak's default "Full group path" on, so the trap shows first
  echo "Step 4: adding the groups claim (Full group path ON - Keycloak's default)..."
  kc create "clients/$cid/protocol-mappers/models" -r "$REALM" -s name=groups -s protocol=openid-connect \
    -s protocolMapper=oidc-group-membership-mapper \
    -s 'config={"claim.name":"groups","full.path":"true","id.token.claim":"true","access.token.claim":"true","userinfo.token.claim":"true"}' >/dev/null

  # 5. Ops Signals settings (step 3), kept out of .env
  echo "Step 5: writing $ENV_FILE..."
  local token=""
  if [[ -f "$ENV_FILE" ]]; then
    token="$(grep '^OPS_SIGNALS_API_TOKEN=' "$ENV_FILE" | cut -d= -f2- || true)"
  fi
  [[ -n "$token" ]] || token="$(openssl rand -hex 32)"
  umask 077
  cat >"$ENV_FILE" <<EOF
OPS_SIGNALS_API_TOKEN=$token
OPS_SIGNALS_AUTH_MODE=oidc
OPS_SIGNALS_OIDC_ISSUER_URL=$ISSUER
OPS_SIGNALS_OIDC_CLIENT_ID=$CLIENT
OPS_SIGNALS_OIDC_CLIENT_SECRET=$secret
OPS_SIGNALS_AUTH_ADMIN_GROUPS=ops-signals-admins
OPS_SIGNALS_AUTH_EDITOR_GROUPS=ops-signals-editors
OPS_SIGNALS_OIDC_PROVIDER_NAME="Acme login"
OPS_SIGNALS_PUBLIC_URL=http://localhost:${FRONTEND_PORT}
EOF

  cat <<EOF

Keycloak is ready.
  Keycloak admin console: http://localhost:${KEYCLOAK_PORT}  (admin / admin, realm "$REALM")
  Users: john / Passw0rd-john (Admin) · elena / Passw0rd-elena (Editor) · vic / Passw0rd-vic (Viewer)
  Full group path is ON: john signs in as a Viewer and the chip shows "/ops-signals-admins".
  Then run '$0 path-off', sign out and in again: john is an Admin.
  API token for scripts: OPS_SIGNALS_API_TOKEN in $ENV_FILE

EOF
}

case "${1:-}" in
  up)
    up
    if [[ "${2:-}" != "--no-start" ]]; then
      start_run_all
    fi
    ;;
  start) start_run_all ;;
  path-off) set_full_path false && echo "Full group path OFF: sign out and in again to get your role." ;;
  path-on) set_full_path true && echo "Full group path ON: groups arrive as /paths; sign out and in again to see it." ;;
  down)
    docker rm -f "$CONTAINER" >/dev/null 2>&1 && echo "Keycloak removed." || echo "Keycloak wasn't running."
    rm -f "$ENV_FILE" && echo "Removed $ENV_FILE. Start ./scripts/run_all.sh as usual."
    ;;
  *)
    sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
