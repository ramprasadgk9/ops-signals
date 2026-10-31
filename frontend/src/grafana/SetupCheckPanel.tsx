import React from 'react';
import { useCallback, useEffect, useState } from 'react';
import { getSetupCheck, getSetupSummary, sendTestAlert, testPrometheusConnection } from './backendClient';
import { isGrafanaProxyUrl } from './backendUrlSetting';
import { styles } from './plainUi';
import {
  ACCESS_DOC,
  LOGIN_STEPS,
  SETUP_GROUPS,
  checksIn,
  connectionTestText,
  fixLabel,
  hasFixDetails,
  loginStepStates,
  setupBanner,
  setupChips,
  setupDocsUrl,
  setupReport,
  setupSummary,
  proxyUnreachableSetupResult,
  unreachableSetupResult,
  type LoginStepState,
  type SetupCheck,
  type SetupCheckResult,
  type SetupCheckStatus,
  type SetupChipTone,
} from '../utils/setupCheck';

// The Setup check inside Grafana: on the plugin's Configuration page (the full list), and as a
// banner above the app while something it needs is broken. The web UI has its own page for it.

export const PLUGIN_CONFIG_PATH = '/plugins/breezypoppy3596-opssignals-app?page=configuration';
export const PLUGIN_APP_PATH = '/a/breezypoppy3596-opssignals-app/ops-signals';

const ICONS: Record<SetupCheckStatus, { mark: string; style: React.CSSProperties; label: string }> = {
  ok: { mark: '✓', style: { background: '#73bf69', color: '#111217' }, label: 'Works' },
  fail: { mark: '!', style: { background: '#f2495c', color: '#111217' }, label: 'Needs fixing' },
  warn: { mark: '!', style: { background: '#ffb357', color: '#111217' }, label: 'Worth doing' },
  off: { mark: '–', style: { border: '1.5px solid rgba(204, 204, 220, 0.45)', color: 'rgba(204, 204, 220, 0.45)' }, label: 'Not set up' },
};

const local = {
  smallButton: { border: '1px solid rgba(204, 204, 220, 0.25)', borderRadius: 4, padding: '4px 10px', background: 'transparent', color: 'inherit', fontSize: 12, cursor: 'pointer', whiteSpace: 'nowrap' },
  row: { display: 'grid', gridTemplateColumns: '22px minmax(140px, 200px) minmax(0, 1fr) auto', gap: 12, alignItems: 'center', padding: '10px 4px', borderTop: '1px solid rgba(204, 204, 220, 0.08)' },
  icon: { width: 20, height: 20, borderRadius: '50%', display: 'grid', placeItems: 'center', fontSize: 12, fontWeight: 700, boxSizing: 'border-box' },
  groupTitle: { fontSize: 12, letterSpacing: '.07em', textTransform: 'uppercase', color: 'rgba(204, 204, 220, 0.66)', fontWeight: 600, margin: '18px 0 4px' },
  label: { color: 'rgba(204, 204, 220, 0.66)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 4 },
  code: { margin: '6px 0 0', background: '#0b0c0f', border: '1px solid rgba(204, 204, 220, 0.12)', borderRadius: 4, padding: '10px 12px', whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 12.5 },
  tile: { border: '1px solid rgba(204, 204, 220, 0.12)', borderRadius: 6, padding: '10px 14px' },
} satisfies Record<string, React.CSSProperties>;

/** Whether this Grafana user may open the plugin's Configuration page (org Admin or server admin).
 * Read from the boot data Grafana puts on every page; without it, assume yes and let Grafana decide. */
export function canOpenPluginConfig(): boolean {
  const user = (window as { grafanaBootData?: { user?: { orgRole?: string; isGrafanaAdmin?: boolean } } }).grafanaBootData?.user;
  if (!user) return true;
  return user.orgRole === 'Admin' || Boolean(user.isGrafanaAdmin);
}

function backendHost(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

/** The check for one backend, refetched when the backend changes; failures become a failed Backend check. */
/** grafanaTarget: the backend URL Grafana calls, when backendUrl is the Grafana proxy. summaryOnly: names
 * and statuses without details, which every role may read (the header chips and the reminder). */
export function useSetupCheck(backendUrl: string, grafanaTarget?: string, summaryOnly = false) {
  const [result, setResult] = useState<SetupCheckResult | null>(null);
  // True when the check itself couldn't be fetched; result then holds a failed Backend check.
  const [unreachable, setUnreachable] = useState(false);
  const [checking, setChecking] = useState(false);
  const run = useCallback(async () => {
    if (!backendUrl) return;
    setChecking(true);
    try {
      setResult(await (summaryOnly ? getSetupSummary : getSetupCheck)(backendUrl));
      setUnreachable(false);
    } catch (error) {
      setResult(
        isGrafanaProxyUrl(backendUrl)
          ? proxyUnreachableSetupResult(error, grafanaTarget ?? 'the backend')
          : unreachableSetupResult(error, backendHost(backendUrl))
      );
      setUnreachable(true);
    } finally {
      setChecking(false);
    }
  }, [backendUrl, grafanaTarget, summaryOnly]);
  useEffect(() => {
    setResult(null);
    void run();
  }, [run]);
  return { result, unreachable, checking, run };
}

const STEP_LOOK: Record<LoginStepState, { mark?: string; style: React.CSSProperties }> = {
  done: { mark: '✓', style: { background: '#73bf69', border: '1.5px solid #73bf69', color: '#111217' } },
  now: { style: { border: '1.5px solid #ffb357', color: '#ffb357' } },
  fail: { mark: '!', style: { background: '#f2495c', border: '1.5px solid #f2495c', color: '#111217' } },
  todo: { style: { border: '1.5px solid rgba(204, 204, 220, 0.45)', color: 'rgba(204, 204, 220, 0.45)' } },
};
const STEP_STATE_LABEL: Record<LoginStepState, string> = { done: 'done', now: 'next', fail: 'needs fixing', todo: 'not yet' };

/** Login's three steps (docs/access.md): lock the API, give people roles, check it. */
function LoginStepStrip({ check }: { check: SetupCheck }) {
  const states = loginStepStates(check);
  if (!states) return null;
  return (
    <ol aria-label="Steps to control who can use Ops Signals" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, listStyle: 'none', margin: 0, padding: '10px 4px 0' }}>
      {LOGIN_STEPS.map((label, index) => {
        const state = states[index];
        return (
          <li key={label} aria-label={`Step ${index + 1}, ${label}: ${STEP_STATE_LABEL[state]}`} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {index > 0 && <span aria-hidden style={{ width: 36, height: 1.5, background: states[index - 1] === 'done' && state !== 'todo' ? '#73bf69' : 'rgba(204, 204, 220, 0.2)' }} />}
            <span aria-hidden style={{ ...local.icon, ...STEP_LOOK[state].style }}>{STEP_LOOK[state].mark ?? index + 1}</span>
            <span style={{ fontSize: 13, fontWeight: state === 'now' || state === 'fail' ? 600 : 400, opacity: state === 'todo' ? 0.66 : 1 }}>{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function CheckRow({ check, backendUrl }: { check: SetupCheck; backendUrl: string }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const icon = ICONS[check.status];
  const details = hasFixDetails(check);

  const act = async (work: () => Promise<{ ok: boolean; text: string }>) => {
    setBusy(true);
    try {
      setNote(await work());
    } catch (error) {
      setNote({ ok: false, text: error instanceof Error ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <LoginStepStrip check={check} />
      <div style={local.row}>
        <span role="img" aria-label={icon.label} style={{ ...local.icon, ...icon.style }}>{icon.mark}</span>
        <span style={{ fontWeight: 500 }}>{check.title}</span>
        <span>
          <span style={{ ...styles.muted, fontSize: 13 }}>{check.detail}</span>
          {note && <span role="status" style={{ display: 'block', fontSize: 12, marginTop: 4, color: note.ok ? '#73bf69' : '#f2495c' }}>{note.text}</span>}
        </span>
        <span style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          {details ? (
            <button type="button" style={local.smallButton} aria-expanded={open} aria-label={`${open ? 'Hide' : fixLabel(check)}: ${check.title}`} onClick={() => setOpen(!open)}>
              {open ? 'Hide' : fixLabel(check)}
            </button>
          ) : check.docs && check.status !== 'ok' ? (
            <a style={{ ...local.smallButton, textDecoration: 'none' }} href={setupDocsUrl(check.docs)} target="_blank" rel="noreferrer">Guide</a>
          ) : null}
          {check.step === 3 && check.status === 'ok' && (
            <a style={{ ...local.smallButton, textDecoration: 'none' }} href={`${setupDocsUrl(ACCESS_DOC)}#what-each-role-can-do`} target="_blank" rel="noreferrer">Who can do what</a>
          )}
          {check.action === 'test_connection' && (
            <button type="button" style={local.smallButton} disabled={busy} aria-label={`Test ${check.title}`}
              onClick={() => act(async () => {
                const result = await testPrometheusConnection(backendUrl, check.connection_id ?? 'default');
                return { ok: result.available, text: connectionTestText(result) };
              })}>
              {busy ? 'Testing…' : 'Test'}
            </button>
          )}
          {check.action === 'send_test_alert' && (
            <button type="button" style={local.smallButton} disabled={busy}
              onClick={() => act(async () => {
                await sendTestAlert(backendUrl);
                return { ok: true, text: 'Test alert sent. Check again to see it counted.' };
              })}>
              Send test alert
            </button>
          )}
          {check.action === 'run_analysis' && (
            <a style={{ ...local.smallButton, textDecoration: 'none' }} href={PLUGIN_APP_PATH}>Run first analysis</a>
          )}
        </span>
      </div>
      {open && details && (
        <div style={{ margin: '0 0 6px 34px', border: `1px solid ${check.status === 'fail' ? 'rgba(242, 73, 92, 0.3)' : 'rgba(204, 204, 220, 0.16)'}`, borderRadius: 6, padding: '12px 14px', display: 'grid', gridTemplateColumns: check.tried || check.cause ? 'repeat(auto-fit, minmax(260px, 1fr))' : '1fr', gap: 18 }}>
          {(check.tried || check.cause) && (
            <div>
              {check.tried && (
                <>
                  <div style={local.label}>What we tried</div>
                  <pre style={local.code}>{check.tried}</pre>
                </>
              )}
              {check.cause && (
                <>
                  <div style={{ ...local.label, marginTop: check.tried ? 12 : 0 }}>Likely cause</div>
                  <div>{check.cause}</div>
                </>
              )}
            </div>
          )}
          <div>
            <div style={local.label}>{fixLabel(check)}</div>
            <ol style={{ margin: '4px 0 0', paddingLeft: 18 }}>
              {(check.fix ?? []).map((step) => <li key={step} style={{ margin: '3px 0' }}>{step}</li>)}
            </ol>
            {check.snippet && <pre style={local.code}>{check.snippet}</pre>}
            {check.docs && (
              <div style={{ ...styles.muted, fontSize: 12, marginTop: 8 }}>
                Full guide: <a href={setupDocsUrl(check.docs)} target="_blank" rel="noreferrer" style={{ color: '#6e9fff' }}>{check.docs.replace(/^docs\//, '')}</a>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function SetupCheckPanel({ backendUrl, grafanaTarget }: { backendUrl: string; grafanaTarget?: string }) {
  const { result, checking, run } = useSetupCheck(backendUrl, grafanaTarget);
  const viaGrafana = isGrafanaProxyUrl(backendUrl);
  const [copied, setCopied] = useState('');
  const summary = result ? setupSummary(result) : null;

  const copy = async () => {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(setupReport(result));
      setCopied('Copied.');
    } catch {
      setCopied("Couldn't copy: the browser blocked the clipboard.");
    }
  };

  return (
    <section aria-label="Setup check" style={styles.stack}>
      <div style={styles.rowBetween}>
        <div>
          <h3 style={{ margin: 0 }}>Setup check</h3>
          <p style={{ ...styles.muted, margin: '4px 0 0' }}>
            Checks each part of Ops Signals at <code>{backendHost(viaGrafana ? grafanaTarget ?? backendUrl : backendUrl)}</code>
            {viaGrafana ? ', reached through Grafana,' : ''} and tells you what to fix. Nothing here changes your settings.
          </p>
        </div>
        <div style={styles.row}>
          {copied && <span role="status" style={{ ...styles.muted, fontSize: 12 }}>{copied}</span>}
          <button type="button" style={local.smallButton} disabled={!result} onClick={copy}>Copy report</button>
          <button type="button" style={styles.button} disabled={checking} onClick={() => void run()}>{checking ? 'Checking…' : 'Check again'}</button>
        </div>
      </div>

      {!result ? (
        <p style={{ ...styles.muted, margin: 0 }}>Checking every part of the setup… this takes a few seconds.</p>
      ) : (
        <>
          {summary && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10 }}>
              <div style={local.tile}><b style={{ fontSize: 20, fontWeight: 500 }}>{summary.requiredDone} of {summary.requiredTotal}</b><div style={{ ...styles.muted, fontSize: 12 }}>needed to start: done</div></div>
              <div style={local.tile}><b style={{ fontSize: 20, fontWeight: 500, color: summary.recommendedOpen ? '#ffb357' : '#73bf69' }}>{summary.recommendedOpen}</b><div style={{ ...styles.muted, fontSize: 12 }}>recommended before others use it</div></div>
              <div style={local.tile}><b style={{ fontSize: 20, fontWeight: 500, color: 'rgba(204, 204, 220, 0.45)' }}>{summary.optionalOff}</b><div style={{ ...styles.muted, fontSize: 12 }}>optional extras not set up</div></div>
            </div>
          )}
          <div>
            {SETUP_GROUPS.map((group) => {
              const checks = checksIn(result, group.id);
              if (!checks.length) return null;
              return (
                <section key={group.id} aria-label={group.title}>
                  <div style={local.groupTitle}>
                    {group.title} <span style={{ textTransform: 'none', letterSpacing: 0, fontWeight: 400, marginLeft: 6 }}>{group.hint}</span>
                  </div>
                  {checks.map((check) => <CheckRow key={check.id} check={check} backendUrl={backendUrl} />)}
                </section>
              );
            })}
          </div>
        </>
      )}
    </section>
  );
}

/** Above the app while something needed is broken; nothing otherwise, and nothing when the check itself
 * can't be fetched (the Backend chip already says the backend is unreachable). */
export function PluginSetupBanner({ result, unreachable }: { result: SetupCheckResult | null; unreachable: boolean }) {
  const message = result && !unreachable ? setupBanner(result) : null;
  if (!message) return null;
  return (
    <div role="status" style={{ ...styles.rowBetween, border: '1px solid rgba(255, 179, 87, 0.4)', background: 'rgba(255, 179, 87, 0.07)', borderRadius: 6, padding: '10px 14px' }}>
      <span>{message}</span>
      {canOpenPluginConfig() ? (
        <a href={PLUGIN_CONFIG_PATH} style={{ ...local.smallButton, textDecoration: 'none' }}>Open Setup check</a>
      ) : (
        <span style={{ ...styles.muted, fontSize: 12 }}>Ask a Grafana admin to open Ops Signals → Configuration.</span>
      )}
    </div>
  );
}

const CHIP_COLORS: Record<SetupChipTone, string> = { ok: '#3fcf8e', warn: '#ffb357', fail: '#f2495c', off: 'rgba(204, 204, 220, 0.55)', pending: 'rgba(204, 204, 220, 0.55)', user: 'inherit' };
const USER_CHIP: React.CSSProperties = { borderColor: 'rgba(87, 148, 242, 0.45)', background: 'rgba(87, 148, 242, 0.1)' };

/** The app header's Backend / Metrics / Case memory chips, from the Setup check (hover for details). */
export function SetupChips({ result, unreachable }: { result: SetupCheckResult | null; unreachable: boolean }) {
  return (
    <>
      {setupChips(result, unreachable).map((chip) => (
        <span key={chip.id} title={chip.title} style={{ ...styles.chip, color: CHIP_COLORS[chip.tone], ...(chip.tone === 'user' ? USER_CHIP : {}) }}>
          {chip.tone === 'user' ? chip.label : `● ${chip.label}`}
        </span>
      ))}
    </>
  );
}
