# Sourced by scripts/run_all.sh. Whether to start the bundled Prometheus and mock metrics: only while
# Ops Signals reads them. Once .env points at your own Prometheus or Mimir they would only use memory.
# OPS_SIGNALS_LOCAL_PROMETHEUS=true or false overrides the guess.

wants_local_prometheus() {
  case "$(echo "${OPS_SIGNALS_LOCAL_PROMETHEUS:-}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) return 0 ;;
    0|false|no|off) return 1 ;;
  esac
  # Alert enrichment's demo alert rules run in the bundled Prometheus.
  case "$(echo "${OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED:-false}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) return 0 ;;
  esac
  if [[ -n "${OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE:-}" ]]; then
    return 1
  fi
  local url="${OPS_SIGNALS_PROMETHEUS_URL:-}"
  url="${url%/}"
  case "$url" in
    ""|http://localhost:9090|http://127.0.0.1:9090) return 0 ;;
  esac
  return 1
}
