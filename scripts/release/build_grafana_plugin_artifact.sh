#!/usr/bin/env bash
set -euo pipefail

# Builds the Grafana plugin zip: dist/release/<release>/<plugin-id>-<plugin version>.zip, laid out as
# Grafana expects (one top-level folder named after the plugin id). <release> is the optional first
# argument, the project release it ships with (e.g. 0.6.4); it defaults to the plugin version. The zip
# is always named after the plugin's own version ("version" in frontend/package.json, 1.0.x; the build
# writes it into plugin.json).
#
# Signing: with GRAFANA_ACCESS_POLICY_TOKEN set (a grafana.com access policy token with the
# plugins:write scope), the plugin is signed before zipping. A community or commercial signature
# needs nothing else; for a private signature also set GRAFANA_SIGN_ROOT_URLS to the Grafana
# address(es) it may run on, comma-separated. Without the token the zip is unsigned.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

read -r PLUGIN_ID PLUGIN_VERSION < <(python3 - "$ROOT_DIR/frontend" <<'PY'
import json
import sys
from pathlib import Path

frontend = Path(sys.argv[1])
plugin = json.loads((frontend / "src" / "plugin.json").read_text())
package = json.loads((frontend / "package.json").read_text())
print(plugin["id"], package["version"])
PY
)

RELEASE="${1:-$PLUGIN_VERSION}"
ARTIFACT_DIR="$ROOT_DIR/dist/release/$RELEASE"
PLUGIN_ZIP="$ARTIFACT_DIR/${PLUGIN_ID}-${PLUGIN_VERSION}.zip"
mkdir -p "$ARTIFACT_DIR"

echo "Building Grafana plugin artifact"
echo "Release:   $RELEASE"
echo "Version:   $PLUGIN_VERSION"
echo "Plugin ID: $PLUGIN_ID"
echo

(
  cd "$ROOT_DIR/frontend"
  npm ci
  npm run build:grafana
)

if [[ -n "${GRAFANA_ACCESS_POLICY_TOKEN:-}" ]]; then
  echo "Signing the plugin"
  SIGN_ARGS=(--distDir dist)
  if [[ -n "${GRAFANA_SIGN_ROOT_URLS:-}" ]]; then
    SIGN_ARGS+=(--rootUrls "$GRAFANA_SIGN_ROOT_URLS")
  fi
  (
    cd "$ROOT_DIR/frontend"
    npx --yes @grafana/sign-plugin@3.3.3 "${SIGN_ARGS[@]}"
  )
  SIGNED="signed"
else
  SIGNED="unsigned: GRAFANA_ACCESS_POLICY_TOKEN not set"
fi

STAGING_DIR="$(mktemp -d)"
trap 'rm -rf "$STAGING_DIR"' EXIT
cp -R "$ROOT_DIR/frontend/dist" "$STAGING_DIR/$PLUGIN_ID"

rm -f "$PLUGIN_ZIP"
(
  cd "$STAGING_DIR"
  zip -qr "$PLUGIN_ZIP" "$PLUGIN_ID"
)

SHA1="$(shasum -a 1 "$PLUGIN_ZIP" | awk '{print $1}')"
echo "$SHA1  $(basename "$PLUGIN_ZIP")" > "$PLUGIN_ZIP.sha1"

echo
echo "Grafana plugin artifact ($SIGNED):"
echo "  $PLUGIN_ZIP"
echo
echo "SHA1 for Grafana plugin submission:"
echo "  $SHA1"
echo
echo "Install it into a Grafana:"
echo "  unzip $(basename "$PLUGIN_ZIP") -d /var/lib/grafana/plugins"
echo
echo "Check it against the catalog rules before submitting:"
echo "  npx --yes @grafana/plugin-validator@0.50.0 -sourceCodeUri file://$ROOT_DIR/frontend $PLUGIN_ZIP"
