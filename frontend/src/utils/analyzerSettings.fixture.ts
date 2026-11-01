// A Settings in use response for tests (GET /api/analyzer-settings).
import type { AnalyzerSettingsResponse } from './analyzerSettings';

const builtin = { layer: 'default' as const, file: 'config/analyzer_registry.d/builtin.yml' };

export const SETTINGS: AnalyzerSettingsResponse = {
  provider: 'prometheus',
  provider_label: 'Prometheus',
  service: null,
  metric: null,
  selection: { mode: 'recommended_threshold', min_score: 0.8, max_analyzers: 3, include_optional: false, selected_analyzers: [], max_analyzers_source: null },
  layers: [
    { key: 'default', title: 'Built-in defaults', file: 'config/analyzer_registry.d/', changed: null, analyzers: 3 },
    { key: 'site', title: 'Your site', file: 'config/analyzers.yaml', exists: true, changed: 1 },
    { key: 'provider', title: 'Data source', file: 'config/providers/prometheus.yaml', exists: true, changed: 0 },
    { key: 'override', title: "A team's services", file: 'config/analyzer_overrides.d/', files: 1, overrides: 1, applied: [], errors: [] },
  ],
  scopes: [{ override_id: 'payments_memory', service: 'payments-api', metric: 'process_resident_memory_bytes', file: 'payments-team.yml', reason: 'Memory grows slowly.' }],
  analyzers: [
    {
      analyzer_id: 'trend',
      display_name: 'Trend Analysis',
      description: 'Spots slow, steady climbs or drops.',
      enabled: true,
      run: { status: 'router', text: 'The router picks it for a metric it suits.' },
      changed_count: 2,
      settings_note: null,
      settings: [
        { path: 'implementation.model', value: 'OLS', default: 'OLS', changed: false, source: builtin, use: 'label', use_note: null, meaning: 'Shown in the finding\'s details only', label: null, per_service: false, min: null, max: null },
        { path: 'finding_rules.min_slope_percent', value: 5, default: 10, changed: true, source: { layer: 'site', file: 'config/analyzers.yaml' }, use: 'used', use_note: null, meaning: 'Smallest steady climb or drop that counts', label: 'Smallest steady climb or drop that counts', per_service: true, min: 1, max: 100 },
        { path: 'finding_rule.min_slope_percent', value: 4, default: null, changed: true, source: { layer: 'site', file: 'config/analyzers.yaml' }, use: 'unknown', use_note: "Trend Analysis doesn't read this key. Check its spelling and where it sits.", meaning: null, label: null, per_service: false, min: null, max: null },
      ],
    },
    {
      analyzer_id: 'anomaly_zscore',
      display_name: 'Z-Score Anomaly',
      description: null,
      enabled: true,
      run: { status: 'only_if_chosen', text: "The router doesn't pick it on its own.", note: 'PyOD Outlier covers spikes by default.' },
      changed_count: 0,
      settings_note: null,
      settings: [{ path: 'finding_rules.min_abs_zscore', value: 3, default: 3, changed: false, source: builtin, use: 'used', use_note: null, meaning: 'How far the most unusual reading must be', label: null, per_service: true, min: 3, max: 10 }],
    },
    {
      analyzer_id: 'prophet',
      display_name: 'Prophet',
      description: null,
      enabled: true,
      run: { status: 'cant_run', text: "Turned on, but the prophet library isn't installed." },
      changed_count: 0,
      settings_note: null,
      settings: [],
    },
  ],
};
