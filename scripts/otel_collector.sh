#!/usr/bin/env bash
# A real OpenTelemetry Collector on this machine, pushing metrics to Ops Signals over OTLP: host
# CPU, memory and load, plus every Docker container's stats (one service per container). For trying
# OTLP ingestion with real metric names instead of the synthetic send_test_otlp_metrics.py series.
#
#   ./scripts/otel_collector.sh start     write tmp/otelcol-local.yaml and start the collector
#   ./scripts/otel_collector.sh status    is it running, and is Ops Signals receiving points
#   ./scripts/otel_collector.sh logs      follow the collector's log
#   ./scripts/otel_collector.sh stop      stop and remove it
#
# Sends to the backend on BACKEND_PORT (default 8001, as run_all.sh). OPS_SIGNALS_API_TOKEN, from
# the environment or .env, is sent as a bearer token when set.
# OTEL_COLLECTOR_CONTAINER and OTEL_COLLECTOR_CONFIG let a second collector run next to this one
# (scripts/otlp_sandbox.sh uses them).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8001}"
CONTAINER="${OTEL_COLLECTOR_CONTAINER:-ops-signals-otel-collector}"
IMAGE="otel/opentelemetry-collector-contrib:latest"
CONFIG="${OTEL_COLLECTOR_CONFIG:-$ROOT_DIR/tmp/otelcol-local.yaml}"

if [[ -z "${OPS_SIGNALS_API_TOKEN:-}" && -f "$ROOT_DIR/.env" ]]; then
  OPS_SIGNALS_API_TOKEN="$(grep -E '^OPS_SIGNALS_API_TOKEN=' "$ROOT_DIR/.env" | tail -1 | cut -d= -f2- || true)"
fi

write_config() {
  mkdir -p "$(dirname "$CONFIG")"
  local headers=""
  if [[ -n "${OPS_SIGNALS_API_TOKEN:-}" ]]; then
    headers=$'\n    headers:\n      Authorization: "Bearer ${env:OPS_SIGNALS_API_TOKEN}"'
  fi
  cat >"$CONFIG" <<EOF
receivers:
  hostmetrics:
    collection_interval: 15s
    scrapers:
      cpu:
      memory:
      load:
  docker_stats:
    endpoint: unix:///var/run/docker.sock
    collection_interval: 15s

processors:
  # One Ops Signals service per container; host metrics go under "local-host".
  transform/service_name:
    metric_statements:
      - context: resource
        statements:
          - set(attributes["service.name"], attributes["container.name"]) where attributes["container.name"] != nil
          - set(attributes["service.name"], "local-host") where attributes["service.name"] == nil
          - set(attributes["deployment.environment"], "local")
  batch:
    timeout: 10s

exporters:
  otlphttp/ops-signals:
    endpoint: http://host.docker.internal:${BACKEND_PORT}/api/otlp${headers}

service:
  pipelines:
    metrics:
      receivers: [hostmetrics, docker_stats]
      processors: [transform/service_name, batch]
      exporters: [otlphttp/ops-signals]
EOF
}

points_received() {
  local auth=()
  [[ -n "${OPS_SIGNALS_API_TOKEN:-}" ]] && auth=(-H "Authorization: Bearer $OPS_SIGNALS_API_TOKEN")
  curl -s -m 5 ${auth[@]+"${auth[@]}"} "http://localhost:${BACKEND_PORT}/api/otlp/status" \
    | python3 -c 'import json, sys; d = json.load(sys.stdin); print("%d points received, %d awaiting analysis" % (d["points_received_total"], d["backlog_size"]))' 2>/dev/null \
    || echo "backend on port ${BACKEND_PORT} not reachable"
}

case "${1:-}" in
  start)
    if ! curl -sf -m 3 "http://localhost:${BACKEND_PORT}/api/health" >/dev/null; then
      echo "Ops Signals isn't answering on port ${BACKEND_PORT}. Start it first (./scripts/run_all.sh)."
      exit 1
    fi
    write_config
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    # root, so the collector can read the Docker socket for container stats
    docker run -d --name "$CONTAINER" --user 0 \
      -e OPS_SIGNALS_API_TOKEN="${OPS_SIGNALS_API_TOKEN:-}" \
      -v "$CONFIG:/etc/otelcol-contrib/config.yaml:ro" \
      -v /var/run/docker.sock:/var/run/docker.sock:ro \
      "$IMAGE" >/dev/null
    echo "Collector started, sending to http://localhost:${BACKEND_PORT}/api/otlp every 15s (config: ${CONFIG#"$ROOT_DIR"/})."
    echo "Waiting for the first batch..."
    sleep 30
    if docker logs "$CONTAINER" 2>&1 | grep -q "Exporting failed"; then
      echo "Exports are failing:"
      docker logs "$CONTAINER" 2>&1 | grep "Exporting failed" | tail -1
      exit 1
    fi
    points_received
    echo "Open Integrations (OTLP tile) and Behavior Lab (type container.mem in Metric name). Findings need some history first."
    ;;
  status)
    if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
      echo "Collector running."
      failures="$(docker logs "$CONTAINER" 2>&1 | grep -c 'Exporting failed' || true)"
      echo "Failed exports so far: ${failures}"
    else
      echo "Collector not running."
    fi
    points_received
    ;;
  logs)
    docker logs -f "$CONTAINER"
    ;;
  stop)
    docker rm -f "$CONTAINER" >/dev/null 2>&1 && echo "Collector stopped." || echo "Collector wasn't running."
    ;;
  *)
    sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
