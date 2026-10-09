import React, { useEffect, useState } from 'react';
import type { FixOutcome, SameFixResponse } from '../types';
import { getCaseSameFix } from './backendClient';
import { styles } from './plainUi';

// "Same fix elsewhere" (other cases this case's cause and fix also resolved) in the Grafana plugin's
// own styling. Same endpoint and wording as the web UI's SameFixElsewhere (components/FixHistory).

const OUTCOME_TONE: Record<FixOutcome['status'], string> = {
  held: '#3fcf8e',
  came_back: '#ffb357',
  too_early: 'rgba(204, 204, 220, 0.72)',
  not_fixed: 'rgba(204, 204, 220, 0.72)',
  unknown: 'rgba(204, 204, 220, 0.72)',
};
const OUTCOME_NOTE = 'A fix "held" when the same problem didn\'t come back on that service within 30 days.';

type State = { status: 'loading' } | { status: 'error' } | { status: 'ready'; data: SameFixResponse };

function OutcomeChip({ outcome }: { outcome: FixOutcome }) {
  const tone = OUTCOME_TONE[outcome.status] ?? OUTCOME_TONE.unknown;
  return <span style={{ ...styles.chip, display: 'inline-block', fontWeight: 700, color: tone, borderColor: `${tone}66` }}>{outcome.label}</span>;
}

/** `refreshKey` reloads the matches after the case's cause or fix is saved. */
export function PluginSameFix({ backendUrl, caseId, refreshKey }: { backendUrl: string; caseId: number; refreshKey?: string }) {
  const [state, setState] = useState<State>({ status: 'loading' });

  useEffect(() => {
    let active = true;
    setState({ status: 'loading' });
    getCaseSameFix(backendUrl, caseId)
      .then((data) => { if (active) setState({ status: 'ready', data }); })
      .catch(() => { if (active) setState({ status: 'error' }); });
    return () => { active = false; };
  }, [backendUrl, caseId, refreshKey]);

  const data = state.status === 'ready' ? state.data : null;
  return (
    <section data-testid="plugin-same-fix" style={{ ...styles.stack, gap: 10, borderTop: '1px solid rgba(204, 204, 220, 0.12)', paddingTop: 12 }}>
      <div>
        <div style={{ ...styles.row, gap: 8 }}>
          <strong>Same fix elsewhere</strong>
          {data?.outcome && data.outcome.status !== 'not_fixed' ? (
            <>
              <span style={styles.muted}>This case's fix:</span>
              <OutcomeChip outcome={data.outcome} />
            </>
          ) : null}
        </div>
        <div style={{ ...styles.helperText, marginTop: 2 }}>Past cases with the same cause and fix, on any service. {OUTCOME_NOTE}</div>
      </div>
      {state.status === 'loading' ? <div style={styles.muted}>Searching past fixes...</div> : null}
      {state.status === 'error' ? <div style={styles.muted}>Past fixes could not be searched. Check the backend connection.</div> : null}
      {data && !data.available ? <div style={styles.muted}>{data.reason ?? 'Operational memory is not available.'}</div> : null}
      {data?.available && !data.matches.length ? <div style={styles.muted}>No other case was fixed this way.</div> : null}
      {data?.available ? data.matches.map((match) => (
        <div key={match.case_id} data-testid="plugin-same-fix-match" style={{ border: '1px solid rgba(204, 204, 220, 0.14)', borderRadius: 8, padding: 12 }}>
          <div style={{ ...styles.row, gap: 8 }}>
            <strong>{match.title}</strong>
            <OutcomeChip outcome={match.outcome} />
          </div>
          <div style={{ ...styles.helperText, marginTop: 4 }}>
            {[`Case #${match.case_id}`, match.service, `${Math.round(match.similarity_score * 100)}% same cause and fix`, match.rca_verified ? 'verified cause' : null].filter(Boolean).join(' · ')}
          </div>
          {match.corrective_action ? <div style={{ fontSize: 13, marginTop: 6 }}><b>Fix:</b> {match.corrective_action}</div> : null}
        </div>
      )) : null}
    </section>
  );
}
