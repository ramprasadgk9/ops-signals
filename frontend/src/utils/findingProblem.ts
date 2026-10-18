import type { Finding } from '../types';

// `ongoing` means the problem was still going on when the analyzed data ended. Only call it
// "still happening" while that data is this recent; an uploaded CSV of last month's metrics ends
// weeks ago, and its problem isn't happening now.
const STILL_HAPPENING_MAX_AGE_MS = 2 * 60 * 60 * 1000;

function at(value: string): string {
  return new Date(value).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function time(value: string): string {
  return new Date(value).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

/** When the problem happened, in words: "Started Oct 12, 09:00 · still happening",
 * "Started Oct 12, 09:00 · still going when the data ended (Oct 12, 10:00)" for data that ended a
 * while ago, or "Oct 12, 09:00–09:45 · over". Null for findings without event times (older ones). */
export function problemTiming(finding: Finding, startedAt?: string, now: number = Date.now()): { label: string; ongoing: boolean } | null {
  if (!finding.event_start || !finding.event_end) return null;
  const start = startedAt && Date.parse(startedAt) < Date.parse(finding.event_start) ? startedAt : finding.event_start;
  if (finding.ongoing) {
    if (now - Date.parse(finding.event_end) <= STILL_HAPPENING_MAX_AGE_MS) return { label: `Started ${at(start)} · still happening`, ongoing: true };
    return { label: `Started ${at(start)} · still going when the data ended (${at(finding.event_end)})`, ongoing: false };
  }
  const sameDay = new Date(start).toDateString() === new Date(finding.event_end).toDateString();
  const end = sameDay ? time(finding.event_end) : at(finding.event_end);
  return { label: `${at(start)}–${end} · over`, ongoing: false };
}
