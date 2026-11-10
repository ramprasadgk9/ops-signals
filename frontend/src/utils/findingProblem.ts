import type { Finding } from '../types';

// `ongoing` means the problem was still going on when the analyzed data ended. Only call it
// "still happening" while that data is this recent; an uploaded CSV of last month's metrics ends
// weeks ago, and its problem isn't happening now.
const STILL_HAPPENING_MAX_AGE_MS = 2 * 60 * 60 * 1000;

/** Whether a problem still going when its data ended is still happening now: the data is recent. */
export function stillHappening(eventEnd: string, now: number = Date.now()): boolean {
  return now - Date.parse(eventEnd) <= STILL_HAPPENING_MAX_AGE_MS;
}

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
  // The problem's end, when the backend found it over (trust.ended_at): a level change that came
  // back still has `ongoing` findings, since its checks run to the last reading.
  const endedAt = finding.trust?.ended_at;
  if (finding.ongoing && !endedAt) {
    if (stillHappening(finding.event_end, now)) return { label: `Started ${at(start)} · still happening`, ongoing: true };
    return { label: `Started ${at(start)} · still going when the data ended (${at(finding.event_end)})`, ongoing: false };
  }
  const endAt = endedAt ?? finding.event_end;
  const sameDay = new Date(start).toDateString() === new Date(endAt).toDateString();
  const end = sameDay ? time(endAt) : at(endAt);
  return { label: `${at(start)}–${end} · over`, ongoing: false };
}
