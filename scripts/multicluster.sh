#!/usr/bin/env bash
# Local multi-cluster Grafana Mimir for testing Ops Signals against several clusters, HA replica
# pairs and two tenants. See docs/testing-multicluster-locally.md.
#
#   ./scripts/multicluster.sh up        start Mimir + 4 Prometheus "clusters", backfill 72h history
#   ./scripts/multicluster.sh app       start Ops Signals (run_all.sh) reading from Mimir tenant team-a
#   ./scripts/multicluster.sh check     verify clusters, replicas, tenants, history (and the app, if running)
#   ./scripts/multicluster.sh status    containers and what is in Mimir
#   ./scripts/multicluster.sh env       print the OPS_SIGNALS_* lines for pointing the backend at Mimir
#   ./scripts/multicluster.sh logs [service]
#   ./scripts/multicluster.sh down      stop, keep data
#   ./scripts/multicluster.sh reset     stop and delete all data (next `up` backfills again)

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/dev/multicluster/docker-compose.yml"
MIMIR_URL="${MIMIR_URL:-http://localhost:9009}"
QUERY_URL="$MIMIR_URL/prometheus"
BACKEND_URL="${BACKEND_URL:-http://localhost:${BACKEND_PORT:-8001}}"
TENANT="${TENANT:-team-a}"

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

say() { printf '%s\n' "$*"; }
ok() { printf '  \033[32mok\033[0m    %s\n' "$*"; }
bad() { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; FAILED=1; }
note() { printf '  \033[33mnote\033[0m  %s\n' "$*"; }

require_docker() {
  if ! docker info >/dev/null 2>&1; then
    say "Docker is not running. Start Docker Desktop and try again."
    exit 1
  fi
}

# GET a Mimir query API path for a tenant; prints the JSON body.
mimir_get() {
  local tenant="$1" path="$2"
  shift 2
  curl -sf -G -H "X-Scope-OrgID: $tenant" "$QUERY_URL/api/v1/$path" "$@"
}

# First result's value, rounded to 1 decimal, or "none" when the query returned nothing.
FIRST_VALUE="round(float(data['data']['result'][0]['value'][1]), 1) if data['data']['result'] else 'none'"

json() {
  python3 -c "import json,sys; data=json.load(sys.stdin); print(eval(sys.argv[1]))" "$1"
}

wait_for_mimir() {
  say "Waiting for Mimir to be ready..."
  for _ in $(seq 1 90); do
    if curl -sf "$MIMIR_URL/ready" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  say "Mimir did not become ready. Check: ./scripts/multicluster.sh logs mimir"
  exit 1
}

wait_for_backfill() {
  say "Writing ${BACKFILL_HOURS:-72}h of history into Mimir (first run only, about a minute)..."
  for _ in $(seq 1 180); do
    local state
    state="$(docker inspect -f '{{.State.Status}} {{.State.ExitCode}}' ops-signals-multicluster-backfill-1 2>/dev/null || echo "missing 0")"
    case "$state" in
      "exited 0") compose logs --no-log-prefix backfill | tail -1; return 0 ;;
      exited*) compose logs backfill | tail -20; say "Backfill failed."; exit 1 ;;
    esac
    sleep 2
  done
  say "Backfill is taking too long. Check: ./scripts/multicluster.sh logs backfill"
  exit 1
}

print_env() {
  cat <<EOF
OPS_SIGNALS_PROMETHEUS_URL=$QUERY_URL
OPS_SIGNALS_PROMETHEUS_HEADERS=X-Scope-OrgID:$TENANT
OPS_SIGNALS_PROMETHEUS_CLUSTER_LABEL=cluster
OPS_SIGNALS_PROMETHEUS_REPLICA_LABELS=__replica__,prometheus_replica
EOF
}

cmd_up() {
  require_docker
  compose up -d
  wait_for_mimir
  wait_for_backfill
  say ""
  say "Multi-cluster Mimir is running."
  say ""
  say "  Mimir query API   $QUERY_URL   (header X-Scope-OrgID: team-a or team-b)"
  say "  Prometheus UIs    eu-a http://localhost:9191  eu-b http://localhost:9192"
  say "                    us   http://localhost:9193  staging http://localhost:9194"
  say ""
  say "  tenant team-a  cluster eu (HA pair, prometheus_replica a/b) + cluster us (checkout 3x slower for 15m every 8h)"
  say "  tenant team-b  cluster staging"
  say ""
  say "Next:"
  say "  ./scripts/multicluster.sh check   verify the data"
  say "  ./scripts/multicluster.sh app     start Ops Signals reading from Mimir (stop your usual run_all.sh first)"
}

cmd_app() {
  if [[ -f "$ROOT_DIR/.env" ]] && grep -qE '^\s*OPS_SIGNALS_PROMETHEUS_(URL|HEADERS)=' "$ROOT_DIR/.env"; then
    say "Your .env sets OPS_SIGNALS_PROMETHEUS_URL or _HEADERS, and run_all.sh loads .env after this script,"
    say "so it would point the app back at your usual Prometheus. Comment those lines out and run this again."
    exit 1
  fi
  if ! curl -sf "$MIMIR_URL/ready" >/dev/null 2>&1; then
    say "Mimir is not running. Start it first: ./scripts/multicluster.sh up"
    exit 1
  fi
  say "Starting Ops Signals against Mimir tenant $TENANT:"
  print_env | sed 's/^/  /'
  say ""
  set -a
  eval "$(print_env)"
  set +a
  exec "$ROOT_DIR/scripts/run_all.sh"
}

cmd_check() {
  FAILED=0
  say "Mimir ($QUERY_URL)"
  if ! curl -sf "$MIMIR_URL/ready" >/dev/null 2>&1; then
    bad "Mimir is not running - ./scripts/multicluster.sh up"
    exit 1
  fi
  ok "ready"

  local clusters_a clusters_b
  clusters_a="$(mimir_get team-a label/cluster/values | json "','.join(data['data'])")"
  clusters_b="$(mimir_get team-b label/cluster/values | json "','.join(data['data'])")"
  [[ "$clusters_a" == "eu,us" ]] && ok "tenant team-a has clusters: $clusters_a" || bad "tenant team-a clusters are '$clusters_a', expected eu,us"
  [[ "$clusters_b" == "staging" ]] && ok "tenant team-b has clusters: $clusters_b (tenants are separate)" || bad "tenant team-b clusters are '$clusters_b', expected staging"

  local replicas
  replicas="$(mimir_get team-a query --data-urlencode 'query=count(request_latency_p95{service="checkout",cluster="eu"})' | json "data['data']['result'][0]['value'][1] if data['data']['result'] else 0")"
  [[ "$replicas" == "2" ]] && ok "cluster eu stores both HA copies (prometheus_replica a and b)" || bad "expected 2 copies of checkout in eu, found $replicas"

  local doubled single
  doubled="$(mimir_get team-a query --data-urlencode 'query=sum(rate(http_requests_total{cluster="eu",service="checkout"}[10m]))' | json "$FIRST_VALUE")"
  single="$(mimir_get team-a query --data-urlencode 'query=sum(max without (prometheus_replica) (rate(http_requests_total{cluster="eu",service="checkout"}[10m])))' | json "$FIRST_VALUE")"
  if [[ "$doubled" == "none" ]]; then
    note "no recent eu samples yet (live data catches up within a few minutes of 'up')"
  else
    ok "eu checkout: naive sum ${doubled} req/s vs one copy ${single} req/s (the doubling Ops Signals avoids)"
  fi

  local now hours
  now="$(date +%s)"
  hours="$(mimir_get team-a query_range --data-urlencode 'query=count(request_latency_p95{cluster="us",service="checkout"})' \
    --data-urlencode "start=$((now - 72 * 3600))" --data-urlencode "end=$now" --data-urlencode 'step=1h' \
    | json "len(data['data']['result'][0]['values']) if data['data']['result'] else 0")"
  (( hours >= 60 )) && ok "history: ${hours}h of data queryable" || bad "only ${hours}h of history queryable, expected about 72"

  local peak_us peak_eu
  peak_us="$(mimir_get team-a query --data-urlencode 'query=max_over_time(request_latency_p95{cluster="us",service="checkout"}[24h])' | json "$FIRST_VALUE")"
  peak_eu="$(mimir_get team-a query --data-urlencode 'query=max(max_over_time(request_latency_p95{cluster="eu",service="checkout"}[24h]))' | json "$FIRST_VALUE")"
  [[ "$peak_us" != none && "$peak_eu" != none ]] && (( ${peak_us%.*} > 2 * ${peak_eu%.*} )) && ok "incident only in us: checkout p95 peak ${peak_us}ms in us vs ${peak_eu}ms in eu" || bad "expected a us-only incident; peaks us=${peak_us} eu=${peak_eu}"

  local live
  live="$(mimir_get team-a query --data-urlencode 'query=count(up{job="cluster-metrics"} == 1)' | json "data['data']['result'][0]['value'][1] if data['data']['result'] else 0")"
  [[ "$live" == "3" ]] && ok "live scraping: 3 Prometheus servers in team-a are sending data" || note "live scrape count is $live (expected 3; give it a minute after 'up')"

  say ""
  say "Ops Signals ($BACKEND_URL)"
  if ! curl -sf "$BACKEND_URL/api/health" >/dev/null 2>&1; then
    note "backend not running - start it with ./scripts/multicluster.sh app, then run check again"
  else
    local end start body
    end="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    start="$(date -u -v-1H +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '-1 hour' +%Y-%m-%dT%H:%M:%SZ)"
    body="$(curl -s -X POST "$BACKEND_URL/api/prometheus/preview" -H 'Content-Type: application/json' \
      -d "{\"connection_id\":\"default\",\"query\":\"request_latency_p95{service=\\\"checkout\\\",cluster=\\\"eu\\\"}\",\"start\":\"$start\",\"end\":\"$end\",\"step\":\"1m\"}")"
    local count
    count="$(printf '%s' "$body" | json "data.get('series_count', 'error: ' + str(data.get('detail')))")"
    if [[ "$count" == "1" ]]; then
      ok "backend preview of the eu HA pair returns 1 series (replica copy dropped)"
      printf '%s' "$body" | json "next((w for w in data['warnings'] if 'replica' in w), '')" | sed 's/^/        /'
    elif [[ "$count" == "0" ]]; then
      note "the backend at $BACKEND_URL found no cluster data - it is reading another Prometheus; start it with ./scripts/multicluster.sh app"
    elif [[ "$count" == error* ]]; then
      bad "backend preview failed: $count - is the backend pointed at Mimir? (./scripts/multicluster.sh env)"
    else
      bad "backend preview returned $count series for the eu HA pair, expected 1"
    fi
  fi

  say ""
  if [[ "$FAILED" == "0" ]]; then say "All checks passed."; else say "Some checks failed."; exit 1; fi
}

cmd_status() {
  require_docker
  compose ps --format 'table {{.Service}}\t{{.State}}\t{{.Ports}}'
  if curl -sf "$MIMIR_URL/ready" >/dev/null 2>&1; then
    say ""
    for tenant in team-a team-b; do
      local series
      series="$(mimir_get "$tenant" query --data-urlencode 'query=count({job="cluster-metrics"})' | json "data['data']['result'][0]['value'][1] if data['data']['result'] else 0")"
      say "tenant $tenant: $series series, clusters: $(mimir_get "$tenant" label/cluster/values | json "', '.join(data['data'])")"
    done
  fi
}

case "${1:-}" in
  up) cmd_up ;;
  app) cmd_app ;;
  check) cmd_check ;;
  status) cmd_status ;;
  env) print_env ;;
  logs) shift; require_docker; compose logs -f --tail 100 "$@" ;;
  down) require_docker; compose down ;;
  reset) require_docker; compose down -v ;;
  *)
    sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
