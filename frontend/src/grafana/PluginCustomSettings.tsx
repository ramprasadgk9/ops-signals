import type { Finding } from '../types';
import { CUSTOM_SETTINGS_LABEL, customSettings, customSettingsTooltip, settingValue } from '../utils/customSettings';
import { styles } from './plainUi';

// Per-service analyzer settings a finding was made with, in the plugin's own styling. Same data
// and wording (utils/customSettings) as the web UI's chip and CustomSettingsBox.

const TONE = '#d6a9ef';

export function PluginCustomSettingsChip({ finding }: { finding: Pick<Finding, 'custom_settings'> }) {
  const custom = customSettings(finding);
  if (!custom) return null;
  return (
    <span data-testid="plugin-custom-settings-chip" title={customSettingsTooltip(custom)} style={{ ...styles.chip, color: TONE, borderColor: '#b877d9', background: 'rgba(184, 119, 217, 0.15)' }}>
      {CUSTOM_SETTINGS_LABEL}
    </span>
  );
}

export function PluginCustomSettings({ finding }: { finding: Pick<Finding, 'custom_settings'> }) {
  const custom = customSettings(finding);
  if (!custom) return null;
  const files = [...new Set(custom.overrides.map((override) => override.file).filter(Boolean))];
  return (
    <section data-testid="plugin-custom-settings" style={{ border: '1px solid #b877d9', borderRadius: 6, background: 'rgba(184, 119, 217, 0.08)', padding: '10px 12px' }}>
      <div>
        <strong style={{ color: TONE }}>Found with custom settings</strong>
        {files.length ? <span style={styles.muted}> · {files.join(', ')}</span> : null}
      </div>
      {custom.settings.map((setting) => (
        <div key={`${setting.analyzer_id}.${setting.path}`} style={{ marginTop: 6 }}>
          {setting.analyzer}: {setting.label}: <strong>{settingValue(setting.value)}</strong>{' '}
          <span style={styles.muted}>(default {settingValue(setting.default)})</span>
        </div>
      ))}
      {custom.overrides.map((override) => (
        <div key={override.id} style={{ ...styles.helperText, marginTop: 6 }}>
          {override.reason ? <>Why: {override.reason} · </> : null}override {override.id}{override.file ? ` in ${override.file}` : ''}
        </div>
      ))}
    </section>
  );
}
