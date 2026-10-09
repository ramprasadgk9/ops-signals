import React, { useCallback, useEffect, useState } from 'react';
import type { AlertItem } from '../types';
import { whatChanged } from '../utils/alertChanges';
import { groupAlerts, summarizeAlerts, type AlertGroup, type SeverityKey } from '../utils/alertGroups';
import { breakdownNextStep, breakdownSentence, findingBreakdown } from '../utils/findingBreakdown';
import { listAlerts } from './backendClient';
import { styles } from './plainUi';

// Received alerts (Alertmanager and other sources) in the Grafana plugin's own styling: one row per
// alert rule with when it fired over the last 24 hours, what changed just before (deploys) and where
// (pods), and the case or finding it was linked to. Grouped like the web UI's Alerts page (shared
// utils/alertGroups), refreshed every 30 seconds while shown.

export const WINDOW_HOURS = 24;
const HOUR_MS = 3_600_000;
const REFRESH_MS = 30_000;
const SEVERITY: Record<SeverityKey, { label: string; tone: string }> = {
  critical: { label: 'Critical', tone: '#f2495c' },
  warning: { label: 'Warning', tone: '#ff9830' },
  other: { label: 'Info', tone: 'rgba(204, 204, 220, 0.72)' },
};
const LINK_BUTTON: React.CSSProperties = { border: 0, background: 'transparent', color: '#5794f2', padding: 0, cursor: 'pointer', fontWeight: 600, textAlign: 'left' };

type State = { status: 'loading' } | { status: 'error' } | { status: 'ready'; alerts: AlertItem[]; at: number };

function ago(value: string, now: number) {
  const minutes = Math.max(0, Math.round((now - Date.parse(value)) / 60_000));
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return hours < 48 ? `${hours}h ago` : `${Math.floor(hours / 24)}d ago`;
}

export function PluginAlerts({ backendUrl, onOpenCase }: { backendUrl: string; onOpenCase: (caseId: number) => void }) {
  const [state, setState] = useState<State>({ status: 'loading' });

  const load = useCallback(async () => {
    try {
      const alerts = await listAlerts(backendUrl, { since: new Date(Date.now() - WINDOW_HOURS * HOUR_MS).toISOString(), limit: 500 });
      setState({ status: 'ready', alerts, at: Date.now() });
    } catch {
      // A failed refresh keeps the alerts already shown.
      setState((current) => (current.status === 'ready' ? current : { status: 'error' }));
    }
  }, [backendUrl]);

  useEffect(() => {
    setState({ status: 'loading' });
    void load();
    const timer = window.setInterval(() => void load(), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  const alerts = state.status === 'ready' ? state.alerts : [];
  const summary = summarizeAlerts(alerts);
  return (
    <section data-testid="plugin-alerts" style={{ ...styles.stack, gap: 12 }}>
      <div>
        <strong style={{ fontSize: 16 }}>Received alerts</strong>
        <div style={{ ...styles.helperText, marginTop: 2 }}>
          Last {WINDOW_HOURS} hours, from Alertmanager and other sources, with what changed just before and the finding or case each one was linked to.
        </div>
      </div>
      {state.status === 'loading' ? <div style={styles.muted}>Loading alerts...</div> : null}
      {state.status === 'error' ? <div style={styles.muted}>Could not load received alerts. Check the backend connection.</div> : null}
      {state.status === 'ready' && !alerts.length ? (
        <div style={{ ...styles.muted, border: '1px dashed rgba(204, 204, 220, 0.28)', borderRadius: 8, padding: 14, textAlign: 'center' }}>
          No alerts in the last {WINDOW_HOURS} hours. Connect Alertmanager in the Ops Signals web app (Integrations) to receive them here.
        </div>
      ) : null}
      {state.status === 'ready' && alerts.length ? (
        <>
          <div data-testid="plugin-alert-summary" style={{ ...styles.row, gap: 16 }}>
            <span><strong style={{ color: '#f2495c' }}>{summary.firing}</strong> firing now</span>
            <span><strong style={{ color: '#5794f2' }}>{summary.linked}</strong> linked to a finding</span>
            <span><strong>{summary.resolved}</strong> resolved ({WINDOW_HOURS}h)</span>
          </div>
          <div style={{ ...styles.stack, gap: 0 }}>
            {groupAlerts(alerts).map((group) => <GroupRow key={group.key} group={group} now={state.at} onOpenCase={onOpenCase} />)}
          </div>
        </>
      ) : null}
    </section>
  );
}

/** When each occurrence fired in the window: one bar per occurrence, solid while firing. */
function Strip({ group, now }: { group: AlertGroup; now: number }) {
  const windowStart = now - WINDOW_HOURS * HOUR_MS;
  const tone = SEVERITY[group.severity].tone;
  return (
    <div aria-hidden="true" style={{ position: 'relative', height: 8, borderRadius: 4, background: 'rgba(204, 204, 220, 0.08)', marginTop: 8 }}>
      {group.occurrences.map((alert) => {
        const firing = alert.status === 'firing';
        const start = Math.max(Date.parse(alert.starts_at), windowStart);
        const end = firing || !alert.ends_at ? now : Math.min(Date.parse(alert.ends_at), now);
        if (Number.isNaN(start) || end < windowStart) return null;
        const left = ((start - windowStart) / (now - windowStart)) * 100;
        const width = Math.max(((end - start) / (now - windowStart)) * 100, 0.6);
        return <span key={alert.id} style={{ position: 'absolute', left: `${left}%`, width: `${width}%`, minWidth: 4, top: 0, bottom: 0, borderRadius: 4, background: tone, opacity: firing ? 1 : 0.4 }} />;
      })}
    </div>
  );
}

/** Where (pods) and what changed (deploys) for an alert, worded like the Slack message. */
function Insight({ alert }: { alert: AlertItem }) {
  const changed = whatChanged(alert);
  const breakdown = findingBreakdown({ comparison_json: { breakdown: alert.breakdown } });
  const where = breakdown?.status === 'ok' ? breakdown : null;
  if (!changed && !where) return null;
  return (
    <div style={{ ...styles.stack, gap: 6, marginTop: 8, padding: '8px 10px', borderRadius: 6, background: 'rgba(87, 148, 242, 0.08)', fontSize: 13 }}>
      {where ? (
        <div>
          <b>Where </b>{breakdownSentence(where)}
          <div style={{ ...styles.helperText, marginTop: 2 }}>{breakdownNextStep(where)}</div>
        </div>
      ) : null}
      {changed ? (
        <div>
          <b>What changed</b>
          {changed.lines.map((line) => <div key={line}>{line}</div>)}
          {changed.note ? <div style={{ ...styles.helperText, marginTop: 2 }}>{changed.note}</div> : null}
        </div>
      ) : null}
    </div>
  );
}

function GroupRow({ group, now, onOpenCase }: { group: AlertGroup; now: number; onOpenCase: (caseId: number) => void }) {
  const [open, setOpen] = useState(false);
  const count = group.occurrences.length;
  const severity = SEVERITY[group.severity];
  const caseId = group.occurrences.find((alert) => alert.case_id !== null)?.case_id ?? null;
  return (
    <div data-testid="plugin-alert-group" style={{ borderTop: '1px solid rgba(204, 204, 220, 0.12)', padding: '12px 0' }}>
      <div style={{ ...styles.rowBetween, alignItems: 'flex-start' }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ ...styles.row, gap: 8 }}>
            <strong>{group.alertName}</strong>
            <span style={{ ...styles.chip, fontWeight: 700, color: group.firing ? '#f2495c' : 'rgba(204, 204, 220, 0.72)', borderColor: group.firing ? '#f2495c66' : undefined }}>{group.firing ? 'FIRING' : 'RESOLVED'}</span>
            {group.isTest ? <span style={styles.chip}>TEST</span> : null}
          </div>
          <div style={{ ...styles.muted, fontSize: 13, marginTop: 4 }}>
            <span style={{ color: severity.tone, fontWeight: 700 }}>{severity.label}</span>
            {` · ${group.service ?? 'no service'} · ${count}× in ${WINDOW_HOURS}h · last ${ago(group.lastReceivedAt, now)} · `}
            {caseId !== null ? (
              <button type="button" style={LINK_BUTTON} onClick={() => onOpenCase(caseId)}>linked to Case #{caseId}</button>
            ) : group.link ? (
              <span>linked to {group.link.text}</span>
            ) : (
              <span>no matching finding yet</span>
            )}
          </div>
          <Strip group={group} now={now} />
          <Insight alert={group.occurrences[0]} />
        </div>
        {count > 1 ? (
          <button type="button" style={{ ...LINK_BUTTON, whiteSpace: 'nowrap', marginLeft: 12 }} aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? 'Hide' : `${count} occurrences`}
          </button>
        ) : null}
      </div>
      {open ? (
        <div style={{ ...styles.stack, gap: 6, paddingLeft: 14, marginTop: 8 }}>
          {group.occurrences.map((alert) => (
            <div key={alert.id} data-testid="plugin-alert-occurrence" style={{ fontSize: 13 }}>
              {alert.status === 'firing' ? 'Firing' : 'Resolved'} · received {ago(alert.received_at, now)}
              {alert.summary && alert.summary !== alert.alert_name ? <span style={styles.muted}> · {alert.summary}</span> : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
