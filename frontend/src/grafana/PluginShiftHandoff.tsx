import React, { useEffect, useState } from 'react';
import type { GrafanaCase } from './contracts';
import type { HandoffWatchItem, ShiftHandoff } from '../types';
import { HANDOFF_HOURS, handoffCopyText, handoffCounts, watchLabel } from '../utils/shiftHandoff';
import { getAiStatus, getCase, getShiftHandoff, writeShiftHandoffNote } from './backendClient';
import { InvestigationDrawer } from './PanelPreview';
import { styles } from './plainUi';

// The on-call handoff in the Grafana plugin's own styling. Same endpoints and wording as the web
// UI's ShiftHandoffCard; a case opens in the case drawer, a finding in the overview's panel.

const WATCH: React.CSSProperties = { border: '1px solid #ffb357', borderRadius: 8, padding: 12, background: 'rgba(255, 179, 87, 0.08)' };
const LINK_BUTTON: React.CSSProperties = { border: 0, background: 'transparent', color: '#5794f2', padding: 0, cursor: 'pointer', fontWeight: 600, textAlign: 'left' };

export function PluginShiftHandoff({ backendUrl, onOpenFinding }: { backendUrl: string; onOpenFinding?: (findingId: number) => boolean }) {
  const [hours, setHours] = useState(12);
  const [handoff, setHandoff] = useState<ShiftHandoff | null>(null);
  const [failed, setFailed] = useState(false);
  const [aiActive, setAiActive] = useState(false);
  const [note, setNote] = useState<{ hours: number; text: string | null } | null>(null);
  const [writing, setWriting] = useState(false);
  const [copied, setCopied] = useState('');
  const [openCase, setOpenCase] = useState<GrafanaCase | null>(null);
  const [openError, setOpenError] = useState('');

  useEffect(() => {
    let active = true;
    setFailed(false);
    getShiftHandoff(backendUrl, hours)
      .then((data) => { if (active) setHandoff(data); })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [backendUrl, hours]);

  useEffect(() => {
    let active = true;
    getAiStatus(backendUrl)
      .then((status) => { if (active) setAiActive(status.active === true); })
      .catch(() => undefined);
    return () => { active = false; };
  }, [backendUrl]);

  // As elsewhere on the overview: if this read fails, the page renders as it would without it.
  if (failed) return null;
  const aiNote = note && note.hours === hours ? note.text : null;
  const noteFailed = note !== null && note.hours === hours && !note.text;
  const [first, ...rest] = handoff?.watch ?? [];

  async function write() {
    setWriting(true);
    try {
      const result = await writeShiftHandoffNote(backendUrl, hours);
      setNote({ hours, text: result.available ? result.note ?? null : null });
    } catch {
      setNote({ hours, text: null });
    } finally {
      setWriting(false);
    }
  }

  async function copy() {
    if (!handoff) return;
    try {
      await navigator.clipboard.writeText(handoffCopyText(handoff, aiNote));
      setCopied('Copied. Paste it in your team channel.');
    } catch {
      setCopied("Couldn't copy: the browser blocked the clipboard.");
    }
  }

  async function open(item: HandoffWatchItem) {
    setOpenError('');
    if (item.case_id) {
      try {
        setOpenCase(await getCase(backendUrl, item.case_id));
      } catch {
        setOpenError(`Could not open case #${item.case_id}. Check the backend connection and retry.`);
      }
      return;
    }
    if (!item.finding_id || !onOpenFinding?.(item.finding_id)) setOpenError('This finding is not in the overview window; open it from Findings.');
  }

  return (
    <section data-testid="plugin-shift-handoff" style={{ ...styles.card, ...styles.stack, gap: 10 }}>
      <div style={styles.rowBetween}>
        <div>
          <strong style={{ fontSize: 16 }}>Shift handoff</strong>
          <div style={{ ...styles.helperText, marginTop: 2 }}>For the next person on call: what happened and what to watch first.</div>
        </div>
        <div style={{ ...styles.row, gap: 6 }} role="group" aria-label="Handoff window">
          {HANDOFF_HOURS.map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={value === hours}
              style={{ ...styles.chip, cursor: 'pointer', color: 'inherit', background: value === hours ? 'rgba(87, 148, 242, 0.25)' : 'transparent' }}
              onClick={() => { setHours(value); setCopied(''); }}
            >
              Last {value}h
            </button>
          ))}
        </div>
      </div>

      {!handoff ? <div style={styles.muted}>Loading the handoff...</div> : (
        <>
          <div data-testid="plugin-shift-handoff-counts" style={{ fontWeight: 700 }}>{handoffCounts(handoff)}</div>
          {first ? (
            <div style={{ ...WATCH, ...styles.rowBetween }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ color: '#ffb357', fontSize: 12, fontWeight: 700, textTransform: 'uppercase' }}>Watch first</div>
                <div style={{ fontWeight: 700 }}>{watchLabel(first)}</div>
                <div style={styles.helperText}>{first.title}: {first.reason}</div>
              </div>
              <button type="button" style={styles.button} onClick={() => open(first)}>{first.case_id ? 'Open case' : 'Open finding'}</button>
            </div>
          ) : <div style={styles.muted}>Nothing open needs watching.</div>}
          {rest.length ? (
            <div style={{ ...styles.stack, gap: 4 }}>
              <div style={{ ...styles.helperText, fontWeight: 700 }}>Also worth a look</div>
              {rest.map((item) => (
                <button key={`${item.kind}-${item.case_id ?? item.finding_id}`} type="button" style={LINK_BUTTON} onClick={() => open(item)}>
                  {watchLabel(item)} · <span style={{ fontWeight: 400 }}>{item.reason}</span>
                </button>
              ))}
            </div>
          ) : null}
          {aiNote ? (
            <div data-testid="plugin-shift-handoff-note" style={{ border: '1px solid rgba(204, 204, 220, 0.12)', borderRadius: 8, padding: 12 }}>
              <div style={{ ...styles.helperText, marginTop: 0 }}><span style={styles.chip}>AI</span> Written from the counts and list above. Check it before you paste.</div>
              <div style={{ marginTop: 6 }}>{aiNote}</div>
              <button type="button" style={{ ...LINK_BUTTON, marginTop: 6 }} onClick={() => setNote(null)}>Show plain summary</button>
            </div>
          ) : null}
          {noteFailed ? <div style={styles.helperText}>The AI note couldn't be written. The plain summary is still copied.</div> : null}
          <div style={styles.row}>
            <button type="button" style={styles.button} title="Copies the note and the list. Paste it in your team channel at shift change." onClick={copy}>Copy for Slack</button>
            {aiActive ? (
              <button type="button" style={{ ...styles.button, background: 'transparent', border: '1px solid rgba(204, 204, 220, 0.3)', color: 'inherit' }} disabled={writing} onClick={write}>
                {writing ? 'Writing...' : aiNote ? 'Write again' : 'Write with AI'}
              </button>
            ) : null}
            {copied ? <span role="status" style={styles.helperText}>{copied}</span> : null}
          </div>
          {openError ? <div style={{ ...styles.helperText, color: '#ff7381' }}>{openError}</div> : null}
        </>
      )}
      <InvestigationDrawer
        open={openCase !== null}
        caseResult={null}
        caseDetails={openCase}
        finding={null}
        backendUrl={backendUrl}
        onClose={() => setOpenCase(null)}
        onCaseChange={setOpenCase}
        onError={() => undefined}
      />
    </section>
  );
}
