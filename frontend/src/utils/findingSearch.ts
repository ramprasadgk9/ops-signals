import type { Finding } from '../types';

export type FindingSort = 'latest' | 'oldest' | 'importance' | 'priority';

export const findingSorts: Array<{ id: FindingSort; label: string }> = [
  { id: 'latest', label: 'Latest first' },
  { id: 'oldest', label: 'Oldest first' },
  { id: 'importance', label: 'Most important' },
  { id: 'priority', label: 'Investigation priority' },
];

export function findingSortFromParam(value: string | null): FindingSort {
  return findingSorts.some((item) => item.id === value) ? (value as FindingSort) : 'latest';
}

/** The finding number a search asks for: "#57" or "57"; null otherwise. */
export function findingIdFromQuery(query: string): number | null {
  const match = /^#?(\d+)$/.exec(query.trim());
  return match ? Number(match[1]) : null;
}

function searchableText(finding: Finding): string {
  return [finding.service, finding.metric_name, finding.title, finding.cluster, finding.connection_id, finding.category, finding.health_status]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}

function tokenMatches(finding: Finding, token: string, text: string): boolean {
  // "#57" is a finding number only; a bare "57" is either the number or text (e.g. "p95" for "95").
  if (token.startsWith('#')) return /^#\d+$/.test(token) && finding.id === Number(token.slice(1));
  if (/^\d+$/.test(token) && finding.id === Number(token)) return true;
  return text.includes(token);
}

function time(finding: Finding): number {
  const value = finding.created_at ? Date.parse(finding.created_at) : NaN;
  return Number.isNaN(value) ? 0 : value;
}

const comparators: Record<FindingSort, (a: Finding, b: Finding) => number> = {
  latest: (a, b) => time(b) - time(a) || (b.id ?? 0) - (a.id ?? 0),
  oldest: (a, b) => time(a) - time(b) || (a.id ?? 0) - (b.id ?? 0),
  importance: (a, b) => b.importance_score - a.importance_score || time(b) - time(a),
  priority: (a, b) => a.investigation_priority - b.investigation_priority || b.importance_score - a.importance_score,
};

/** Findings matching every word of `query` (service, metric, title, cluster, connection or #number), sorted. */
export function searchFindings(findings: Finding[], query: string, sort: FindingSort): Finding[] {
  const tokens = query.toLowerCase().split(/\s+/).filter(Boolean);
  const matching = tokens.length
    ? findings.filter((finding) => {
        const text = searchableText(finding);
        return tokens.every((token) => tokenMatches(finding, token, text));
      })
    : findings;
  return [...matching].sort(comparators[sort]);
}

/** One card for findings that repeat across runs: the same kind of change on the same series. */
export type FindingGroup = {
  /** The finding the card shows: the first of the group in the list's sort order. */
  finding: Finding;
  /** Every finding in the group, in the list's sort order (includes `finding`). */
  runs: Finding[];
  firstSeen?: string;
  lastSeen?: string;
  /** The group's most recent finding: it says whether the problem is still going on. */
  latest?: Finding;
  /** The earliest start any of its runs saw: a later run's window may begin after the problem did. */
  startedAt?: string;
};

function repeatKey(finding: Finding): string {
  // Linked by the backend to the problem it repeats (same series, same kind, overlapping time).
  if (finding.event_start) return `problem:${finding.problem_id ?? finding.id}`;
  // Older findings carry no event time: the same kind of change on the same series.
  return JSON.stringify([finding.connection_id ?? null, finding.service ?? null, finding.metric_name, finding.cluster ?? null, finding.category, finding.title]);
}

/**
 * Groups `findings` (already sorted) so each repeated finding appears once, where its first
 * member would have been. With `group` false, every finding is its own group.
 */
export function groupRepeatedFindings(findings: Finding[], group = true): FindingGroup[] {
  const groups = new Map<string, FindingGroup>();
  const ordered: FindingGroup[] = [];
  for (const finding of findings) {
    const key = group ? repeatKey(finding) : `id:${finding.id ?? ordered.length}`;
    let entry = groups.get(key);
    if (!entry) {
      entry = { finding, runs: [] };
      groups.set(key, entry);
      ordered.push(entry);
    }
    entry.runs.push(finding);
  }
  for (const entry of ordered) {
    const times = entry.runs.map((run) => run.created_at).filter((value): value is string => Boolean(value)).sort((a, b) => Date.parse(a) - Date.parse(b));
    entry.firstSeen = times[0];
    entry.lastSeen = times[times.length - 1];
    entry.startedAt = entry.runs.map((run) => run.event_start).filter((value): value is string => Boolean(value)).sort((a, b) => Date.parse(a) - Date.parse(b))[0];
    entry.latest = entry.runs.reduce((latest, run) => (Date.parse(run.created_at ?? '') > Date.parse(latest.created_at ?? '') ? run : latest), entry.runs[0]);
  }
  return ordered;
}
