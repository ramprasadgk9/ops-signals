/**
 * Endpoints for the two real environments this suite runs against:
 *  - web-ui:  scripts/run_all.sh          (frontend :5174 -> backend :8001)
 *  - plugin:  scripts/run_grafana_stack.sh (Grafana :3000  -> backend :8002)
 */
export const env = {
  webUiBaseUrl: process.env.OPS_SIGNALS_WEB_UI_URL ?? 'http://localhost:5174',
  grafanaBaseUrl: process.env.OPS_SIGNALS_GRAFANA_URL ?? 'http://localhost:3000',
  webUiBackendUrl: process.env.OPS_SIGNALS_WEB_UI_BACKEND_URL ?? 'http://localhost:8001',
  pluginBackendUrl: process.env.OPS_SIGNALS_PLUGIN_BACKEND_URL ?? 'http://localhost:8002',
  prometheusUrl: process.env.OPS_SIGNALS_PROMETHEUS_URL ?? 'http://localhost:9090',
  databaseUrl: process.env.OPS_SIGNALS_DATABASE_URL ?? process.env.OPS_INTEL_DATABASE_URL ?? 'postgresql+psycopg://ops_signals:ops_signals@localhost:5432/ops_signals',
  grafanaUser: process.env.OPS_SIGNALS_GRAFANA_USER ?? 'admin',
  grafanaPassword: process.env.OPS_SIGNALS_GRAFANA_PASSWORD ?? 'admin',
  pluginAppPath: '/a/breezypoppy3596-opssignals-app/ops-signals',
};
