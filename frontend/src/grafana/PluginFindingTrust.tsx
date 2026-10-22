import React, { useEffect, useState } from 'react';
import type { FindingTrust, FindingVerdict } from '../types';
import { answerLine, movedNote, serviceCaption, serviceHeadline, serviceLabel, serviceProgress, serviceRateLeads, testedCaption, testedHeadline, testedTooltip, trustBadge, VERDICTS } from '../utils/findingTrust';
import { sendFindingFeedback } from './backendClient';
import { LockReason, LOCK_REASONS, usePermissions } from './permissions';
import { styles } from './plainUi';

// How much to trust a finding, and the "Was this real?" answer that feeds it, in the Grafana plugin's
// own styling. Same wording (utils/findingTrust) and endpoint as the web UI's FindingTrustPanel.

const BADGE_TONE = { success: '#3fcf8e', warning: '#ffb357', error: '#f2495c', default: 'rgba(204, 204, 220, 0.72)' } as const;
const SELECTED: React.CSSProperties = { background: '#5794f2', color: '#fff', border: '1px solid #5794f2' };

function Column({ label, headline, caption, value, tone, info }: { label: string; headline: string; caption: string; value: number | null; tone: string; info?: string }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ ...styles.tableHeader, textTransform: 'uppercase' }} title={info || undefined}>{label}{info ? ' ⓘ' : ''}</div>
      <div style={{ fontSize: 18, fontWeight: 800, lineHeight: 1.3 }}>{headline}</div>
      {value !== null ? (
        <div style={{ height: 6, borderRadius: 4, background: 'rgba(204, 204, 220, 0.12)', margin: '6px 0' }}>
          <div style={{ width: `${Math.round(value * 100)}%`, height: '100%', borderRadius: 4, background: tone }} />
        </div>
      ) : null}
      <div style={{ ...styles.helperText, marginTop: 2 }}>{caption}</div>
    </div>
  );
}

/** Evidence badge, "On your service" next to "In testing", and the "Was this real?" buttons. Context
 * findings that the team's answers didn't move show only the buttons, as in the web UI. Renders
 * nothing for a finding without trust (an older backend). */
export function PluginFindingTrust({ backendUrl, findingId, trust, service }: { backendUrl: string; findingId?: number | null; trust?: FindingTrust | null; service?: string | null }) {
  const { canEdit } = usePermissions();
  const [current, setCurrent] = useState(trust ?? null);
  const [pending, setPending] = useState<FindingVerdict | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setCurrent(trust ?? null);
    setFailed(false);
  }, [findingId, trust]);

  if (!current) return null;

  const answer = async (verdict: FindingVerdict) => {
    if (!findingId) return;
    setPending(verdict);
    setFailed(false);
    try {
      const updated = await sendFindingFeedback(backendUrl, findingId, verdict);
      setCurrent(updated.trust ?? current);
    } catch {
      setFailed(true);
    } finally {
      setPending(null);
    }
  };

  const badge = trustBadge(current);
  const note = movedNote(current, service);
  const answerOnly = current.tier === 'context' && !current.moved;
  const chosen = pending ?? current.your_answer;

  return (
    <section data-testid="plugin-finding-trust" style={{ ...styles.stack, gap: 10, borderTop: '1px solid rgba(204, 204, 220, 0.12)', paddingTop: 12 }}>
      {badge ? (
        <div>
          <span style={{ ...styles.chip, display: 'inline-block', fontWeight: 700, color: BADGE_TONE[badge.color], borderColor: `${BADGE_TONE[badge.color]}66` }}>{badge.label}</span>
          <div style={{ ...styles.helperText, marginTop: 6 }}>{badge.detail}</div>
        </div>
      ) : null}
      {note ? <strong>{note}</strong> : null}
      {answerOnly ? null : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16 }}>
          <Column
            label={serviceLabel(current)}
            headline={serviceHeadline(current)}
            caption={serviceCaption(current, service)}
            value={serviceProgress(current)}
            tone={serviceRateLeads(current) ? '#3fcf8e' : 'rgba(204, 204, 220, 0.6)'}
          />
          <Column
            label="In testing"
            headline={testedHeadline(current)}
            caption={testedCaption(current)}
            value={current.tested ? current.tested.real : null}
            tone="rgba(204, 204, 220, 0.6)"
            info={testedTooltip(current)}
          />
        </div>
      )}
      {findingId ? (
        <div style={{ ...styles.row, gap: 8 }}>
          <span style={styles.muted}>Was this real?</span>
          {VERDICTS.map((verdict) => (
            <button
              key={verdict.id}
              type="button"
              aria-pressed={chosen === verdict.id}
              disabled={pending !== null || !canEdit}
              onClick={() => answer(verdict.id)}
              style={{ ...styles.chip, background: 'transparent', color: canEdit ? 'inherit' : 'rgba(204, 204, 220, 0.35)', cursor: !canEdit ? 'not-allowed' : pending ? 'wait' : 'pointer', ...(chosen === verdict.id ? SELECTED : {}) }}
            >
              {verdict.label}
            </button>
          ))}
          {failed ? <span style={{ ...styles.helperText, margin: 0, color: '#ff7381' }}>Couldn't save your answer.</span> : null}
        </div>
      ) : null}
      {answerLine(current) ? <div style={{ ...styles.helperText, marginTop: 0 }}>{answerLine(current)}</div> : null}
      {findingId && !canEdit ? <LockReason style={{ marginTop: 0 }}>{LOCK_REASONS.answer}</LockReason> : null}
    </section>
  );
}
