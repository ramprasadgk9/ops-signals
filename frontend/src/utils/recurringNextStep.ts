import type { RecurringProblem } from '../types';

type RecurringCause = RecurringProblem['causes'][number];

// What to do about a recurring problem, from the causes recorded on its cases. Shared by the web
// UI's Recurring problems page and the Grafana plugin, so both say the same thing.

export type NextStepTone = 'fix' | 'mixed' | 'verify' | 'record';
export type NextStep = { tone: NextStepTone; title: string; detail: string };

// "Wrong image version." and "wrong image  version" are the same cause; differently worded
// causes still count as different - this compares text, not meaning.
function sameCauseKey(cause: RecurringCause): string {
  return cause.root_cause.trim().toLowerCase().replace(/\s+/g, ' ').replace(/[.!]+$/, '');
}

export function recurringNextStep(problem: RecurringProblem, groupBy: 'symptom' | 'cause'): NextStep {
  if (!problem.causes.length) {
    return { tone: 'record', title: 'No cause recorded yet.', detail: 'Record one on any of these cases so the next person knows.' };
  }
  const verified = problem.causes.filter((cause) => cause.verified);
  if (!verified.length) {
    return {
      tone: 'verify',
      title: 'Cause not verified yet.',
      detail: `${problem.causes.length === 1 ? 'One case has' : `${problem.causes.length} cases have`} a cause written down, none confirmed. Confirm one so its fix can be trusted.`,
    };
  }
  // Grouped by cause, every case in the group already shares it.
  if (groupBy === 'cause') {
    return { tone: 'fix', title: 'Worth a lasting fix.', detail: `The same cause came back ${problem.occurrences} times.` };
  }
  const distinct = new Set(verified.map(sameCauseKey)).size;
  if (distinct === 1) {
    return { tone: 'fix', title: 'Worth a lasting fix.', detail: `Same verified cause each time it was checked: ${verified[0].root_cause}` };
  }
  return {
    tone: 'mixed',
    title: 'Different causes.',
    detail: `${distinct} different verified causes for the same symptom. Group by cause to see which one keeps coming back.`,
  };
}

/** The open case most worth opening to record or confirm a cause: the latest still open, else the latest. */
export function caseToRecordCauseOn(problem: RecurringProblem): number {
  const open = problem.cases.find((item) => !['resolved', 'closed', 'mitigated'].includes(item.case_status));
  return (open ?? problem.cases[0]).case_id;
}

export type CaseRecurrence = { problem: RecurringProblem; lastCause: RecurringCause | null };

/** The recurring problem a case belongs to, if any, and the best cause found on one of the other
 * cases (verified first, then the most recent - the order the backend returns). */
export function recurrenceForCase(problems: RecurringProblem[], caseId: number): CaseRecurrence | null {
  const problem = problems.find((item) => item.cases.some((member) => member.case_id === caseId));
  if (!problem) return null;
  return { problem, lastCause: problem.causes.find((cause) => cause.case_id !== caseId) ?? null };
}
