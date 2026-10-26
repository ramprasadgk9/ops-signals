// Per-service analyzer settings a finding was made with (backend services/finding_settings.py).
// Shared by the web UI and the Grafana plugin, so it stays free of UI imports.
import type { Finding, FindingCustomSettings } from '../types';

export const CUSTOM_SETTINGS_LABEL = 'Custom settings · not tested';

/** Why the tested numbers don't show for a finding made with custom settings. */
export const CUSTOM_SETTINGS_TRUST_NOTE =
  "Tested on public data with the default settings. This finding used settings your team chose, so those numbers don't apply. " +
  '"Was this real?" answers still count toward On your service.';

export function customSettings(finding: Pick<Finding, 'custom_settings'>): FindingCustomSettings | null {
  return finding.custom_settings?.settings?.length ? finding.custom_settings : null;
}

export function settingValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'boolean') return value ? 'on' : 'off';
  return String(value);
}

/** One line per changed setting: "Trend Analysis: Smallest steady climb … : 5 (default 10)". */
export function settingLines(custom: FindingCustomSettings): string[] {
  return custom.settings.map(
    (setting) => `${setting.analyzer}: ${setting.label}: ${settingValue(setting.value)} (default ${settingValue(setting.default)})`
  );
}

/** The card chip's tooltip. */
export function customSettingsTooltip(custom: FindingCustomSettings): string {
  const files = [...new Set(custom.overrides.map((override) => override.file).filter(Boolean))];
  const from = files.length ? ` from ${files.join(', ')}` : '';
  return `Found with per-service settings${from}. ${settingLines(custom).join('. ')}. Open the finding for why.`;
}
