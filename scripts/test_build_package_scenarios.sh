#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-0.1.0-local}"
IMAGE_REGISTRY="${IMAGE_REGISTRY:-local}"
REPORT_DIR="$ROOT_DIR/dist/local-validation"
REPORT_MD="$REPORT_DIR/build-package-report.md"
REPORT_JSON="$REPORT_DIR/build-package-report.jsonl"
PYTHON_BIN="${PYTHON_BIN:-python3}"

mkdir -p "$REPORT_DIR"
: >"$REPORT_JSON"

status="PASS"

record_result() {
  local scenario="$1"
  local surface="$2"
  local input="$3"
  local expected="$4"
  local actual="$5"
  local result="$6"

  SCENARIO="$scenario" SURFACE="$surface" INPUT="$input" EXPECTED="$expected" ACTUAL="$actual" RESULT="$result" \
    "$PYTHON_BIN" -c 'import json, os; print(json.dumps({"scenario": os.environ["SCENARIO"], "surface": os.environ["SURFACE"], "input": os.environ["INPUT"], "expected": os.environ["EXPECTED"], "actual": os.environ["ACTUAL"], "status": os.environ["RESULT"]}))' >>"$REPORT_JSON"
  printf '| %s | %s | `%s` | %s | %s | %s |\n' \
    "$scenario" "$surface" "$input" "$expected" "$actual" "$result" >>"$REPORT_MD"
}

run_scenario() {
  local scenario="$1"
  local surface="$2"
  local input="$3"
  local expected="$4"
  shift 4

  echo
  echo "==> $scenario"
  if "$@"; then
    record_result "$scenario" "$surface" "$input" "$expected" "command completed successfully" "PASS"
  else
    status="FAIL"
    record_result "$scenario" "$surface" "$input" "$expected" "command failed" "FAIL"
    return 1
  fi
}

cat >"$REPORT_MD" <<EOF
# Build, Package, And Image Scenario Report

Version: \`$VERSION\`
Image registry: \`$IMAGE_REGISTRY\`

| Scenario Description | Surface | Input | Expected Outcome | Actual Output | Status |
| --- | --- | --- | --- | --- | --- |
EOF

cd "$ROOT_DIR"

run_scenario \
  "Given standalone web UI source, build TypeScript and Vite production assets without compile errors." \
  "web-ui" \
  "frontend/src, frontend/vite.config.ts" \
  "frontend/dist contains production web assets" \
  npm --prefix frontend run build

run_scenario \
  "Given Grafana plugin source and metadata, build the plugin bundle with plugin.json, README, and image assets." \
  "plugin-ui" \
  "frontend/src/plugin.json, frontend/webpack.config.ts, frontend/.config, frontend/src/grafana, frontend/src/plugin" \
  "frontend/dist contains Grafana plugin bundle metadata and assets" \
  npm --prefix frontend run build:grafana

run_scenario \
  "Given the Grafana plugin bundle, package a release ZIP and generate the SHA1 needed for plugin submission." \
  "release" \
  "scripts/release/build_grafana_plugin_artifact.sh, frontend/dist" \
  "dist/release/$VERSION contains plugin ZIP and printed SHA1" \
  ./scripts/release/build_grafana_plugin_artifact.sh "$VERSION"

if command -v docker >/dev/null 2>&1; then
  run_scenario \
    "Given backend, web, and MCP Dockerfiles, build all deployment images without pushing them." \
    "docker" \
    "docker/backend.Dockerfile, docker/web.Dockerfile, docker/mcp.Dockerfile" \
    "$IMAGE_REGISTRY/ops-signals-backend:$VERSION, web:$VERSION, and mcp:$VERSION images build locally" \
    env IMAGE_REGISTRY="$IMAGE_REGISTRY" ./scripts/release/build_deployment_images.sh "$VERSION"
else
  status="FAIL"
  record_result \
    "Given backend, web, and MCP Dockerfiles, build all deployment images without pushing them." \
    "docker" \
    "docker/backend.Dockerfile, docker/web.Dockerfile, docker/mcp.Dockerfile" \
    "Docker images build locally" \
    "docker command not found" \
    "FAIL"
fi

if command -v helm >/dev/null 2>&1; then
  run_scenario \
    "Given Helm chart templates and values, render Kubernetes manifests without template errors." \
    "helm" \
    "helm/ops-signals/Chart.yaml, helm/ops-signals/values.yaml, helm/ops-signals/templates" \
    "helm lint and helm template succeed" \
    bash -c 'helm lint helm/ops-signals && helm template ops-signals helm/ops-signals >/dev/null'
else
  record_result \
    "Given Helm chart templates and values, render Kubernetes manifests without template errors." \
    "helm" \
    "helm/ops-signals" \
    "helm lint/template can run when Helm is installed" \
    "helm command not found; skipped locally" \
    "SKIPPED"
fi

echo
echo "Report written:"
echo "  $REPORT_MD"
echo "  $REPORT_JSON"

if [[ "$status" != "PASS" ]]; then
  exit 1
fi
