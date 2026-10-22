// A combined pattern is a behavior finding: one rule (config/behavior_definitions.d) that matched
// several metrics together on one service. These helpers turn its stored facts into what the
// Findings page shows - each metric with its shape and change, why it matched, and which
// single-metric findings it was made from.
import type { BehaviorFinding, Finding } from '../types';

export type PatternWindow = '6h' | '24h' | '7d';

export type PatternPart = {
  alias: string;
  metric: string;
  /** Plain shape, e.g. "Slowly rising" - the same words as the Behavior Lab pattern cards. */
  shape: string;
  /** Signed percent change, when the analyzer reported one. */
  change: number | null;
  start: string | null;
  end: string | null;
};

type Facts = Record<string, any>;

const WINDOW_HOURS: Record<PatternWindow, number> = { '6h': 6, '24h': 24, '7d': 24 * 7 };

/** Backend timestamps are UTC; some arrive without a zone, which Date would read as local time. */
export function parseUtc(value?: string | null): number {
  if (!value) return Number.NaN;
  const iso = value.includes('T') ? value : value.replace(' ', 'T');
  return new Date(/(Z|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`).getTime();
}

function largestLevelChange(facts: Facts): number | null {
  const changes = [facts.baseline_shift, facts.ruptures]
    .filter((item) => item?.present)
    .map((item) => Number(item.signed_change_percent ?? 0));
  if (!changes.length) return null;
  return changes.reduce((best, value) => (Math.abs(value) > Math.abs(best) ? value : best), 0);
}

/** Which shape a metric showed, most specific first: a level jump, then a trend, then a spike. */
function shapeOf(facts: Facts): { shape: string; change: number | null } {
  const level = largestLevelChange(facts);
  if (level !== null) return { shape: 'Jumps to a new level', change: level };
  if (facts.trend?.present) {
    const percent = Number(facts.trend.change_percent ?? 0);
    if (facts.trend.direction === 'downward') return { shape: 'Slowly falling', change: percent ? -percent : null };
    if (facts.trend.direction === 'upward') return { shape: 'Slowly rising', change: percent || null };
    return { shape: 'Stays flat', change: null };
  }
  if (facts.anomaly?.present) return { shape: 'Unusual spike', change: null };
  return { shape: 'No change found', change: null };
}

/** One entry per rule input, in the rule's order. */
export function patternParts(behavior: Pick<BehaviorFinding, 'input_metrics_json' | 'facts_json'>): PatternPart[] {
  return Object.entries(behavior.input_metrics_json ?? {}).map(([alias, metric]) => {
    const facts: Facts = (behavior.facts_json?.[alias] as Facts) ?? {};
    return {
      alias,
      metric: String(metric),
      ...shapeOf(facts),
      start: facts.signal?.window_start ?? null,
      end: facts.signal?.window_end ?? null,
    };
  });
}

export function formatChange(change: number | null): string | null {
  if (change === null || !Number.isFinite(change)) return null;
  const rounded = Math.round(change);
  return `${rounded > 0 ? '+' : ''}${rounded}%`;
}

export function conditionsPassed(behavior: Pick<BehaviorFinding, 'matched_conditions_json'>): { passed: number; total: number } {
  const conditions = behavior.matched_conditions_json ?? [];
  return { passed: conditions.filter((item) => item.passed === true).length, total: conditions.length };
}

/** How long the metrics' windows overlapped, when the rule checked timing and it passed. */
export function overlapMinutes(behavior: Pick<BehaviorFinding, 'correlation_json'>): number | null {
  const correlation = behavior.correlation_json ?? {};
  if (correlation.matched !== true || typeof correlation.overlap_minutes !== 'number') return null;
  return Math.round(correlation.overlap_minutes);
}

export function inWindow(behavior: Pick<BehaviorFinding, 'last_seen_at'>, window: PatternWindow, now = Date.now()): boolean {
  const seen = parseUtc(behavior.last_seen_at);
  return Number.isFinite(seen) && now - seen <= WINDOW_HOURS[window] * 3600_000;
}

/** Same words the Findings search matches: title, service, and every metric the rule used. */
export function searchPatterns(behaviors: BehaviorFinding[], query: string): BehaviorFinding[] {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return behaviors;
  return behaviors.filter((behavior) => {
    const text = [behavior.title, behavior.service, ...patternParts(behavior).map((part) => part.metric)].join(' ').toLowerCase();
    return terms.every((term) => text.includes(term));
  });
}

/**
 * The single-metric findings a pattern was made from: same service, one of the rule's metrics, and
 * found by the same analysis run the pattern last matched in. Keyed by finding id; a finding can
 * belong to more than one pattern.
 */
export function patternsByFinding(behaviors: BehaviorFinding[], findings: Finding[]): Map<number, BehaviorFinding[]> {
  const byFinding = new Map<number, BehaviorFinding[]>();
  for (const behavior of behaviors) {
    if (!behavior.analysis_run_id) continue;
    const metrics = new Set(patternParts(behavior).map((part) => part.metric));
    for (const finding of findings) {
      if (finding.id === undefined || finding.id === null) continue;
      if (finding.analysis_run_id !== behavior.analysis_run_id) continue;
      if ((finding.service ?? null) !== (behavior.service ?? null) || !metrics.has(finding.metric_name)) continue;
      byFinding.set(finding.id, [...(byFinding.get(finding.id) ?? []), behavior]);
    }
  }
  return byFinding;
}

/** The findings each pattern was made from, the other way round. */
export function partFindings(behavior: BehaviorFinding, byFinding: Map<number, BehaviorFinding[]>, findings: Finding[]): Finding[] {
  return findings.filter((finding) => finding.id != null && (byFinding.get(finding.id) ?? []).some((item) => item.id === behavior.id));
}

/** Still going on (seen by a run in the last 24 hours) or quiet since. */
export function patternStatus(behavior: BehaviorFinding, now = Date.now()): 'active' | 'quiet' {
  return inWindow(behavior, '24h', now) ? 'active' : 'quiet';
}

/** The smallest Findings window that still lists the pattern; null when it is older than all of them. */
export function findingsWindowFor(behavior: Pick<BehaviorFinding, 'last_seen_at'>, now = Date.now()): PatternWindow | null {
  return (['6h', '24h', '7d'] as PatternWindow[]).find((window) => inWindow(behavior, window, now)) ?? null;
}

/** Where "View details" opens the pattern: its card on the Findings page. */
export function patternFindingsHref(behavior: Pick<BehaviorFinding, 'id' | 'last_seen_at'>, now = Date.now()): string | null {
  const window = findingsWindowFor(behavior, now);
  return window ? `/findings?window=${window}&pattern=${behavior.id}` : null;
}
