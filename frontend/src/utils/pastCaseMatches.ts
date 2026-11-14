import type { PastCaseMatch } from '../types';

/** Same service first; within each group, the server's order. The backend ranks matches by
 * similarity plus small bonuses (shared keywords, verified root cause, recency), so re-sorting by
 * score here would undo that. A possible match on this service is more useful than a strong-looking
 * one elsewhere. Shared by the web UI and the Grafana plugin so both list matches the same way. */
export function rankPastMatches(matches: PastCaseMatch[]) {
  return [...matches].sort((a, b) => Number(Boolean(b.same_service)) - Number(Boolean(a.same_service)));
}

export type MatchOutcomePart = { label: string; text: string; unconfirmed?: boolean };

/** The one line under a past-case match that says what happened, best evidence first: a fix with
 * its cause, a cause not yet verified, the case's guided investigation, or that nothing is recorded.
 * Imported postmortems count as verified: they were written after the incident was closed. */
export function matchOutcome(match: PastCaseMatch): { parts: MatchOutcomePart[]; empty?: string } {
  const resolved = (match.case_status ?? '').toLowerCase() === 'resolved';
  const imported = match.origin === 'imported';
  const verified = imported || Boolean(match.rca_verified);
  const cause = match.root_cause_summary?.trim();
  const fix = (match.corrective_action || match.outcome_summary)?.trim();
  if (cause || fix) {
    const parts: MatchOutcomePart[] = [];
    if (fix) parts.push({ label: resolved ? 'Fixed' : 'Fix', text: fix });
    if (cause) parts.push(verified ? { label: 'Cause', text: cause } : { label: 'Likely cause', text: cause, unconfirmed: true });
    // An unconfirmed cause reads first, so the warning isn't hidden behind the fix.
    return { parts: verified ? parts : parts.reverse() };
  }
  if (match.investigation_ending === 'nothing_found') return { parts: [{ label: 'Investigated', text: 'nothing found yet.' }] };
  const lead = match.investigation_summary?.trim();
  if (lead) return { parts: [{ label: 'Investigating', text: lead }] };
  return { parts: [], empty: resolved ? 'Resolved, nothing recorded.' : 'Open, nothing recorded yet.' };
}

/** "Resolved · cause verified", "In progress", "Open": the case's state, for the match footer. */
export function matchStatus(match: PastCaseMatch): { label: string; detail?: string; tone: 'resolved' | 'progress' | 'open' } {
  const status = (match.case_status ?? 'open').toLowerCase();
  if (status === 'resolved') {
    if (match.origin === 'imported') return { label: 'Resolved', detail: 'past incident', tone: 'resolved' };
    return { label: 'Resolved', detail: match.rca_verified ? 'cause verified' : 'cause not verified', tone: 'resolved' };
  }
  if (status === 'in_progress' || status === 'investigating') return { label: 'In progress', tone: 'progress' };
  return { label: 'Open', tone: 'open' };
}

/** "1 of them was fixed." under the Seen before header, so it's clear up front whether there's an answer. */
export function fixedCountSentence(matches: PastCaseMatch[]): string | null {
  if (!matches.length) return null;
  const fixed = matches.filter((match) => (match.case_status ?? '').toLowerCase() === 'resolved' && Boolean(match.corrective_action || match.outcome_summary)).length;
  if (!fixed) return matches.length === 1 ? "It wasn't fixed yet." : 'None of them was fixed yet.';
  if (matches.length === 1) return 'It was fixed.';
  return `${fixed} of them ${fixed === 1 ? 'was' : 'were'} fixed.`;
}

/** "Nov 2" (or "Nov 2, 2025" outside this year): when the past case was opened. */
export function matchDate(value?: string | null, now: Date = new Date()): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString(undefined, date.getFullYear() === now.getFullYear() ? { month: 'short', day: 'numeric' } : { month: 'short', day: 'numeric', year: 'numeric' });
}
