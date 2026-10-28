import React, { useEffect, useState } from 'react';
import type { CameBackAfterFix, FixCameBackWhy, FixOutcome } from '../types';
import { CAME_BACK_RULE, cameBackHeadline, daysBadge, didNotHoldHeadline, fixedOn, whyUnavailable } from '../utils/fixCameBack';
import { getAiStatus, getFixCameBackWhy } from './backendClient';
import { styles } from './plainUi';

// "The fix that didn't stick" in the plugin's own styling, like the web UI's FixCameBack.tsx.

const AMBER = '#ffb357';
const BANNER: React.CSSProperties = { ...styles.alert, borderColor: 'rgba(255, 179, 87, 0.5)', background: 'rgba(255, 179, 87, 0.08)' };
const AI_BUTTON: React.CSSProperties = { border: '1px solid rgba(184, 119, 217, 0.6)', background: 'transparent', color: '#b877d9', borderRadius: 4, padding: '4px 10px', cursor: 'pointer', fontWeight: 600 };

type Subject = { kind: 'cases' | 'findings'; id: number };

/** "This came back N days after it was fixed." On a case, `onCase` names the old case in the headline. */
export function PluginFixCameBackBanner({ backendUrl, cameBack, subject, onCase = false, note }: {
  backendUrl: string;
  cameBack: CameBackAfterFix;
  subject: Subject;
  onCase?: boolean;
  note?: string;
}) {
  const badge = daysBadge(cameBack.days);
  return (
    <div data-testid="plugin-fix-came-back" style={BANNER}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        <div style={{ textAlign: 'center', minWidth: 40, color: AMBER }}>
          <div style={{ fontSize: 22, fontWeight: 900, lineHeight: 1.1 }}>{badge.value}</div>
          <div style={{ fontSize: 11, fontWeight: 700 }}>{badge.unit}</div>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <strong>{cameBackHeadline(cameBack, onCase)}</strong>
          {onCase ? null : <div style={{ marginTop: 4 }}>Case #{cameBack.case_id} {cameBack.title} was resolved on {fixedOn(cameBack.fixed_at)}.</div>}
          <div style={{ marginTop: 2 }}><b>Fix then:</b> {cameBack.fix}</div>
          {cameBack.still_open ? <div style={{ ...styles.muted, marginTop: 2 }}>Still open on that case: {cameBack.still_open}</div> : null}
          {note ? <div style={{ ...styles.muted, marginTop: 2 }}>{note}</div> : null}
          <div style={styles.helperText}>{CAME_BACK_RULE}</div>
          <PluginWhy backendUrl={backendUrl} subject={subject} />
        </div>
      </div>
    </div>
  );
}

/** On the old case: its fix came back in a later case. The case stays resolved. */
export function PluginFixDidNotHold({ outcome, note }: { outcome: FixOutcome; note?: string }) {
  const headline = didNotHoldHeadline(outcome);
  if (!headline) return null;
  return (
    <div data-testid="plugin-fix-did-not-hold" style={BANNER}>
      <strong><span style={{ color: AMBER }} aria-hidden>↻ </span>{headline}</strong>
      <div style={{ ...styles.muted, marginTop: 4 }}>Worth recording a lasting fix on case #{outcome.came_back_case_id}.{note ? ` ${note}` : ''}</div>
    </div>
  );
}

type WhyState = { status: 'idle' } | { status: 'pending' } | { status: 'done'; result: FixCameBackWhy };

function PluginWhy({ backendUrl, subject }: { backendUrl: string; subject: Subject }) {
  const [aiActive, setAiActive] = useState(false);
  const [state, setState] = useState<WhyState>({ status: 'idle' });
  useEffect(() => {
    let active = true;
    getAiStatus(backendUrl).then((status) => { if (active) setAiActive(status.active); }).catch(() => undefined);
    return () => { active = false; };
  }, [backendUrl]);
  if (!aiActive) return null;

  const ask = () => {
    setState({ status: 'pending' });
    getFixCameBackWhy(backendUrl, subject.kind, subject.id)
      .then((result) => setState({ status: 'done', result }))
      .catch(() => setState({ status: 'done', result: { available: false, reasons: [], reason_code: 'failed' } }));
  };
  const result = state.status === 'done' ? state.result : null;
  return (
    <div style={{ marginTop: 8 }}>
      {result?.available ? null : (
        <button type="button" style={AI_BUTTON} onClick={ask} disabled={state.status === 'pending'}>
          {state.status === 'pending' ? 'Comparing…' : '✦ Why might it not have held?'}
        </button>
      )}
      {result && !result.available ? <div style={{ ...styles.muted, marginTop: 6 }}>{whyUnavailable(result.reason_code)}</div> : null}
      {result?.available ? (
        <div data-testid="plugin-fix-came-back-why" style={{ border: '1px solid rgba(184, 119, 217, 0.4)', borderRadius: 6, padding: 10 }}>
          <div style={{ ...styles.row, justifyContent: 'space-between' }}>
            <b>Possible reasons</b>
            <span style={{ ...styles.chip, color: '#b877d9' }}>AI · not saved</span>
          </div>
          <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
            {result.reasons.map((reason) => <li key={reason}>{reason}</li>)}
          </ul>
          <div style={styles.helperText}>Written from the past case and this problem only. Check before acting.</div>
        </div>
      ) : null}
    </div>
  );
}
