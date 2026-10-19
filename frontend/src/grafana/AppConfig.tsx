import React from 'react';
import { useState } from 'react';
import { getBackendSrv } from '@grafana/runtime';
import { Field, styles } from './plainUi';
import { ApiTokenField } from './ApiTokenField';
import { configuredBackendUrl, defaultBackendUrl, isValidBackendUrl, normalizeBackendUrl, type PluginJsonData } from './backendUrlSetting';
import { SetupCheckPanel } from './SetupCheckPanel';

type AppConfigMeta = {
  id: string;
  enabled?: boolean;
  pinned?: boolean;
  jsonData?: PluginJsonData & Record<string, unknown>;
};

type SaveSettings = (pluginId: string, settings: { enabled: boolean; pinned: boolean; jsonData: Record<string, unknown> }) => Promise<unknown>;

const saveWithGrafana: SaveSettings = (pluginId, settings) =>
  getBackendSrv().post(`/api/plugins/${pluginId}/settings`, settings);

// The plugin's Configuration page (Administration -> Plugins -> Ops Signals). Saving reloads the page
// so the app picks the new backend up everywhere.
export function AppConfig({
  plugin,
  save = saveWithGrafana,
  reload = () => window.location.reload(),
}: {
  plugin: { meta: AppConfigMeta };
  save?: SaveSettings;
  reload?: () => void;
}) {
  const { meta } = plugin;
  const [backendUrl, setBackendUrl] = useState(configuredBackendUrl(meta.jsonData) ?? '');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  // Bumped when the API token changes, so the Setup check runs again with it.
  const [tokenVersion, setTokenVersion] = useState(0);
  // The backend the app uses now: the saved URL, else the build default or the local stack.
  const activeBackendUrl = defaultBackendUrl(meta.jsonData, import.meta.env.VITE_OPS_SIGNALS_BACKEND_URL);
  const invalid = backendUrl.trim() !== '' && !isValidBackendUrl(backendUrl);

  const submit = async (enabled: boolean) => {
    setSaving(true);
    setError('');
    try {
      await save(meta.id, {
        enabled,
        pinned: enabled,
        // Grafana merges jsonData into what it has, so clearing must send '' rather than drop the key.
        jsonData: { ...(meta.jsonData ?? {}), backendUrl: normalizeBackendUrl(backendUrl) },
      });
      reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save the plugin settings.');
      setSaving(false);
    }
  };

  return (
    <div style={styles.stack}>
      <h3 style={{ margin: 0 }}>Ops Signals backend</h3>
      <p style={{ margin: 0 }}>
        The address of your Ops Signals backend, as the browser reaches it, for example{' '}
        <code>https://ops-signals.example.internal</code>. Add this Grafana's address to the backend's{' '}
        <code>OPS_SIGNALS_CORS_ORIGINS</code> so the browser may call it.
      </p>
      <Field label="Backend URL">
        <input
          aria-label="Backend URL"
          style={styles.input}
          value={backendUrl}
          onChange={(event) => setBackendUrl(event.target.value)}
          placeholder="http://localhost:8000"
        />
      </Field>
      {invalid && <p role="alert" style={{ margin: 0 }}>Enter an http:// or https:// URL.</p>}
      {error && <p role="alert" style={{ margin: 0 }}>{error}</p>}
      <div style={{ display: 'flex', gap: 8 }}>
        <button type="button" style={styles.button} disabled={saving || invalid} onClick={() => submit(true)}>
          {meta.enabled ? 'Save settings' : 'Enable and save'}
        </button>
        {meta.enabled && (
          <button type="button" style={styles.button} disabled={saving} onClick={() => submit(false)}>
            Disable plugin
          </button>
        )}
      </div>
      <div style={{ maxWidth: 420 }}>
        <ApiTokenField onSaved={() => setTokenVersion((version) => version + 1)} />
        <p style={{ ...styles.helperText, marginTop: 4 }}>Kept in this browser only. Each person enters it once in their own browser.</p>
      </div>
      <hr style={{ border: 0, borderTop: '1px solid rgba(204, 204, 220, 0.12)', width: '100%', margin: '8px 0' }} />
      <SetupCheckPanel key={`${activeBackendUrl}#${tokenVersion}`} backendUrl={activeBackendUrl} />
    </div>
  );
}
