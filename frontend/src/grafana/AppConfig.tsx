import React from 'react';
import { useState } from 'react';
import { getBackendSrv } from '@grafana/runtime';
import { Field, styles } from './plainUi';
import { ApiTokenField } from './ApiTokenField';
import {
  activeBackendUrl,
  configuredBackendUrl,
  configuredWebUiUrl,
  connectMode,
  isValidBackendUrl,
  normalizeBackendUrl,
  type ConnectMode,
  type PluginJsonData,
} from './backendUrlSetting';
import { SetupCheckPanel } from './SetupCheckPanel';

type AppConfigMeta = {
  id: string;
  enabled?: boolean;
  pinned?: boolean;
  jsonData?: PluginJsonData & Record<string, unknown>;
  // Which encrypted settings are set; Grafana never sends their values to the browser.
  secureJsonFields?: Record<string, boolean>;
};

type PluginSettings = {
  enabled: boolean;
  pinned: boolean;
  jsonData: Record<string, unknown>;
  secureJsonData?: Record<string, string>;
};
type SaveSettings = (pluginId: string, settings: PluginSettings) => Promise<unknown>;

const saveWithGrafana: SaveSettings = (pluginId, settings) =>
  getBackendSrv().post(`/api/plugins/${pluginId}/settings`, settings);

const choiceStyle = (on: boolean): React.CSSProperties => ({
  display: 'grid',
  gridTemplateColumns: '20px 1fr',
  gap: 10,
  alignItems: 'start',
  border: `1px solid ${on ? '#5794f2' : 'rgba(204, 204, 220, 0.2)'}`,
  background: on ? 'rgba(87, 148, 242, 0.08)' : 'transparent',
  borderRadius: 6,
  padding: '12px 14px',
  cursor: 'pointer',
});
const tagStyle = (tone: 'green' | 'grey'): React.CSSProperties => ({
  fontSize: 11,
  borderRadius: 999,
  padding: '1px 8px',
  marginLeft: 6,
  border: `1px solid ${tone === 'green' ? 'rgba(115, 191, 105, 0.5)' : 'rgba(204, 204, 220, 0.2)'}`,
  color: tone === 'green' ? '#73bf69' : 'rgba(204, 204, 220, 0.66)',
});
const pointsStyle: React.CSSProperties = { margin: '6px 0 0', paddingLeft: 16, color: 'rgba(204, 204, 220, 0.66)', fontSize: 12.5 };

function ConnectChoice({ mode, value, title, tag, points, onChange }: {
  mode: ConnectMode;
  value: ConnectMode;
  title: string;
  tag: { label: string; tone: 'green' | 'grey' };
  points: string[];
  onChange: (mode: ConnectMode) => void;
}) {
  return (
    <label style={choiceStyle(mode === value)}>
      <input type="radio" name="connect-through" checked={mode === value} onChange={() => onChange(value)} style={{ margin: '3px 0 0' }} />
      <span>
        <b>{title}</b>
        <span style={tagStyle(tag.tone)}>{tag.label}</span>
        <ul style={pointsStyle}>
          {points.map((point) => <li key={point}>{point}</li>)}
        </ul>
      </span>
    </label>
  );
}

// The plugin's Configuration page (Administration -> Plugins -> Ops Signals). Saving reloads the page
// so the app picks the new settings up everywhere.
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
  const savedUrl = configuredBackendUrl(meta.jsonData);
  // A new install starts on Grafana; one saved before the choice existed keeps calling directly.
  const [mode, setMode] = useState<ConnectMode>(meta.jsonData?.connectMode ?? (savedUrl ? 'direct' : 'grafana'));
  const [backendUrl, setBackendUrl] = useState(savedUrl ?? '');
  const [webUiUrl, setWebUiUrl] = useState(configuredWebUiUrl(meta.jsonData) ?? '');
  const [secureToken, setSecureToken] = useState('');
  const [tokenReset, setTokenReset] = useState(false);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  // Bumped when the browser's API token changes, so the Setup check runs again with it.
  const [tokenVersion, setTokenVersion] = useState(0);
  const viaGrafana = mode === 'grafana';
  const tokenConfigured = Boolean(meta.secureJsonFields?.apiToken) && !tokenReset;
  const invalid = backendUrl.trim() !== '' && !isValidBackendUrl(backendUrl);
  const invalidWebUi = webUiUrl.trim() !== '' && !isValidBackendUrl(webUiUrl);
  const missingUrl = viaGrafana && backendUrl.trim() === '';
  // The Setup check runs against what is saved, which is what the app uses.
  const checkedUrl = activeBackendUrl(meta.jsonData, import.meta.env.VITE_OPS_SIGNALS_BACKEND_URL);
  const savedViaGrafana = connectMode(meta.jsonData) === 'grafana';

  const submit = async (enabled: boolean) => {
    setSaving(true);
    setError('');
    const token = secureToken.trim();
    try {
      await save(meta.id, {
        enabled,
        pinned: enabled,
        // Grafana merges jsonData into what it has, so clearing must send '' rather than drop the key.
        jsonData: { ...(meta.jsonData ?? {}), backendUrl: normalizeBackendUrl(backendUrl), connectMode: mode, webUiUrl: normalizeBackendUrl(webUiUrl) },
        // Only sent when it changes: Grafana keeps an encrypted value it isn't sent, and '' removes it.
        ...(token ? { secureJsonData: { apiToken: token } } : tokenReset ? { secureJsonData: { apiToken: '' } } : {}),
      });
      reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save the plugin settings.');
      setSaving(false);
    }
  };

  return (
    <div style={styles.stack}>
      <div>
        <h3 style={{ margin: 0 }}>Ops Signals backend</h3>
        <p style={{ ...styles.muted, margin: '4px 0 0' }}>Where the Ops Signals backend is, and how this Grafana talks to it. Set once for everyone.</p>
      </div>

      <div role="radiogroup" aria-label="Connect through">
        <div style={styles.label}>Connect through</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
          <ConnectChoice
            mode={mode}
            value="grafana"
            title="Grafana"
            tag={{ label: 'Recommended', tone: 'green' }}
            points={[
              'Everyone uses Ops Signals as their own Grafana user, nothing to enter',
              'The API token stays on this Grafana server, never in a browser',
              'Cases, answers and schedules record who did what',
            ]}
            onChange={setMode}
          />
          <ConnectChoice
            mode={mode}
            value="direct"
            title="Browser, directly"
            tag={{ label: 'Development', tone: 'grey' }}
            points={[
              'Each browser calls the backend itself',
              'Each person enters the token in their own browser',
              "Needs Grafana's address in OPS_SIGNALS_CORS_ORIGINS; no names recorded",
            ]}
            onChange={setMode}
          />
        </div>
      </div>

      <div style={{ maxWidth: 560 }}>
        <Field label={viaGrafana ? 'Backend URL, as this Grafana server reaches it' : "Backend URL, as people's browsers reach it"}>
          <input
            aria-label="Backend URL"
            style={styles.input}
            value={backendUrl}
            onChange={(event) => setBackendUrl(event.target.value)}
            placeholder={viaGrafana ? 'http://host.docker.internal:8002' : 'http://localhost:8000'}
          />
        </Field>
        <p style={{ ...styles.helperText, marginTop: 4 }}>
          {viaGrafana ? (
            <>
              Grafana makes the calls, so use an address the Grafana server can reach. With Grafana in Docker and the backend on the same
              computer, that is <code>host.docker.internal</code>, not <code>localhost</code>.
            </>
          ) : (
            <>
              Add this Grafana's address to the backend's <code>OPS_SIGNALS_CORS_ORIGINS</code> so the browser may call it.
            </>
          )}
        </p>
      </div>

      <div style={{ maxWidth: 560 }}>
        {viaGrafana ? (
          <>
            {tokenConfigured ? (
              // Not a <label>: a button inside one would be named after the whole label.
              <div>
                <div style={styles.label}>API token (only if the backend sets OPS_SIGNALS_API_TOKEN)</div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <div aria-label="API token" style={{ ...styles.input, display: 'flex', alignItems: 'center', color: '#73bf69' }}>● Configured</div>
                  <button type="button" style={{ ...styles.button, background: 'transparent', border: '1px solid rgba(204, 204, 220, 0.25)', color: 'inherit', fontWeight: 400 }} onClick={() => setTokenReset(true)}>
                    Reset
                  </button>
                </div>
              </div>
            ) : (
              <Field label="API token (only if the backend sets OPS_SIGNALS_API_TOKEN)">
                <input
                  aria-label="API token"
                  style={styles.input}
                  type="password"
                  autoComplete="off"
                  value={secureToken}
                  placeholder="Not needed if the backend has no token"
                  onChange={(event) => setSecureToken(event.target.value)}
                />
              </Field>
            )}
            <p style={{ ...styles.helperText, marginTop: 4 }}>Stored encrypted by Grafana. Nobody can read it back, not even admins; Reset replaces it.</p>
          </>
        ) : (
          <>
            <ApiTokenField onSaved={() => setTokenVersion((version) => version + 1)} />
            <p style={{ ...styles.helperText, marginTop: 4 }}>Kept in this browser only. Each person enters it once in their own browser.</p>
          </>
        )}
      </div>

      <div style={{ maxWidth: 560 }}>
        <Field label="Ops Signals web UI address (optional)">
          <input
            aria-label="Web UI address"
            style={styles.input}
            value={webUiUrl}
            onChange={(event) => setWebUiUrl(event.target.value)}
            placeholder="http://localhost:5174"
          />
        </Field>
        <p style={{ ...styles.helperText, marginTop: 4 }}>
          As people's browsers reach it. Behavior findings then link to it, where admins write and change the patterns. Leave empty for no links.
        </p>
      </div>

      {invalid && <p role="alert" style={{ margin: 0 }}>Enter an http:// or https:// URL.</p>}
      {invalidWebUi && <p role="alert" style={{ margin: 0 }}>Enter the web UI address as an http:// or https:// URL.</p>}
      {missingUrl && <p style={{ margin: 0, color: '#ffb357' }}>Enter the backend URL Grafana should call.</p>}
      {error && <p role="alert" style={{ margin: 0 }}>{error}</p>}
      <div style={{ display: 'flex', gap: 8 }}>
        <button type="button" style={styles.button} disabled={saving || invalid || invalidWebUi || missingUrl} onClick={() => submit(true)}>
          {meta.enabled ? 'Save settings' : 'Enable and save'}
        </button>
        {meta.enabled && (
          <button type="button" style={styles.button} disabled={saving} onClick={() => submit(false)}>
            Disable plugin
          </button>
        )}
      </div>

      <hr style={{ border: 0, borderTop: '1px solid rgba(204, 204, 220, 0.12)', width: '100%', margin: '8px 0' }} />
      <SetupCheckPanel key={`${checkedUrl}#${tokenVersion}`} backendUrl={checkedUrl} grafanaTarget={savedViaGrafana ? savedUrl : undefined} />
    </div>
  );
}
