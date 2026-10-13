import type { Finding } from '../types';

function at(value: string): string {
  return new Date(value).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function time(value: string): string {
  return new Date(value).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

/** When the problem happened, in words: "Started Oct 12, 09:00 · still happening" or
 * "Oct 12, 09:00–09:45 · over". Null for findings without event times (older ones). */
export function problemTiming(finding: Finding, startedAt?: string): { label: string; ongoing: boolean } | null {
  if (!finding.event_start || !finding.event_end) return null;
  const start = startedAt && Date.parse(startedAt) < Date.parse(finding.event_start) ? startedAt : finding.event_start;
  if (finding.ongoing) return { label: `Started ${at(start)} · still happening`, ongoing: true };
  const sameDay = new Date(start).toDateString() === new Date(finding.event_end).toDateString();
  const end = sameDay ? time(finding.event_end) : at(finding.event_end);
  return { label: `${at(start)}–${end} · over`, ongoing: false };
}
