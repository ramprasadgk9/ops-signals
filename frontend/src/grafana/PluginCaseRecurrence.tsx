import React, { useEffect, useState } from 'react';
import { getCaseFixCameBack, getRecurringProblems } from './backendClient';
import { PluginFixCameBackBanner, PluginFixDidNotHold } from './PluginFixCameBack';
import { didNotHoldHeadline } from '../utils/fixCameBack';
import type { CaseFixCameBack } from '../types';
import { styles } from './plainUi';
import { recurrenceForCase, type CaseRecurrence } from '../utils/recurringNextStep';

// The window the Recurring problems section opens on, so the count matches what it shows.
const WINDOW_DAYS = 90;

/** "Seen before" in the plugin's case drawer, like the web UI's CaseRecurrenceBanner: when the case
 * is one of a problem that keeps coming back, say how often and what was found last time. A case back
 * soon after an earlier fix, or whose own fix came back, gets that banner instead. */
export function PluginCaseRecurrence({ backendUrl, caseId }: { backendUrl: string; caseId?: number | null }) {
  const [recurrence, setRecurrence] = useState<CaseRecurrence | null>(null);
  const [fix, setFix] = useState<CaseFixCameBack | null>(null);
  useEffect(() => {
    setRecurrence(null);
    setFix(null);
    if (!backendUrl || !caseId) return;
    let active = true;
    // Optional context: any failure just leaves the banner out, never breaks the drawer.
    Promise.resolve()
      .then(() => getRecurringProblems(backendUrl, WINDOW_DAYS, 'symptom', 3, false))
      .then((data) => { if (active && data.available) setRecurrence(recurrenceForCase(data.problems, caseId)); })
      .catch(() => undefined);
    Promise.resolve()
      .then(() => getCaseFixCameBack(backendUrl, caseId))
      .then((data) => { if (active && data.available) setFix(data); })
      .catch(() => undefined);
    return () => { active = false; };
  }, [backendUrl, caseId]);
  const seen = recurrence ? `Seen ${recurrence.problem.occurrences} times in the last ${WINDOW_DAYS} days (Memory & Alerts → Recurring problems).` : undefined;
  if (fix?.came_back && caseId) {
    return <PluginFixCameBackBanner backendUrl={backendUrl} cameBack={fix.came_back} subject={{ kind: 'cases', id: caseId }} onCase note={seen} />;
  }
  if (fix?.fix_outcome && didNotHoldHeadline(fix.fix_outcome)) return <PluginFixDidNotHold outcome={fix.fix_outcome} note={seen} />;
  if (!recurrence) return null;
  const { problem, lastCause } = recurrence;
  return (
    <div data-testid="plugin-case-recurrence" style={{ ...styles.alert, borderColor: 'rgba(255, 179, 87, 0.5)', background: 'rgba(255, 179, 87, 0.08)' }}>
      <strong>Seen before: this problem happened {problem.occurrences} times in the last {WINDOW_DAYS} days.</strong>
      <div style={{ ...styles.muted, marginTop: 4 }}>
        {lastCause
          ? <>Found {lastCause.verified ? 'and verified ' : ''}on case #{lastCause.case_id}: {lastCause.root_cause}{lastCause.fix ? <> — fixed by: {lastCause.fix}</> : null}</>
          : 'No cause recorded on the other cases yet.'}
        {' '}The whole pattern is under Memory &amp; Alerts → Recurring problems.
      </div>
    </div>
  );
}
