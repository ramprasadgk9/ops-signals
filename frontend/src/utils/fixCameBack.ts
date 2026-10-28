import type { CameBackAfterFix, FixOutcome } from '../types';

// Wording for "the fix that didn't stick" (backend/app/memory/fix_came_back.py), shared by the web
// UI and the Grafana plugin so both say the same thing.

export const CAME_BACK_RULE = 'Same problem on the same service within 30 days of a fix.';

/** "3 days", "1 day", or "less than a day". */
export function afterDays(days: number): string {
  if (days < 1) return 'less than a day';
  return `${days} ${days === 1 ? 'day' : 'days'}`;
}

/** The big number on the banner: "3" over "days", or "<1" over "day". */
export function daysBadge(days: number): { value: string; unit: string } {
  return days < 1 ? { value: '<1', unit: 'day' } : { value: String(days), unit: days === 1 ? 'day' : 'days' };
}

export function cameBackHeadline(cameBack: CameBackAfterFix, nameCase = false): string {
  return `This came back ${afterDays(cameBack.days)} after ${nameCase ? `case #${cameBack.case_id}` : 'it'} was fixed.`;
}

/** "Oct 24" in the viewer's time zone. */
export function fixedOn(iso: string): string {
  // The backend sends UTC without a zone; without the Z it would read as local time.
  const date = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

/** On the old case, when its own fix came back. */
export function didNotHoldHeadline(outcome: FixOutcome): string | null {
  if (outcome.status !== 'came_back' || outcome.came_back_case_id == null) return null;
  return `This fix didn't hold: the problem came back ${afterDays(outcome.came_back_after_days ?? 0)} later in case #${outcome.came_back_case_id}.`;
}

export function whyUnavailable(reasonCode?: string | null): string {
  if (reasonCode === 'not_enough') return 'Not enough in the cases to say why.';
  if (reasonCode === 'ai_off') return 'AI is off on this server.';
  return "Couldn't get an answer this time. Try again.";
}
