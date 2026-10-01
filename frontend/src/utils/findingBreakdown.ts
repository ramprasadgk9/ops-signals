import type { Finding } from '../types';

// The finding drill-down (backend/app/autonomous/drilldown.py) stored in comparison_json.breakdown:
// which pods (or instances) a service-level change came from. Absent on findings from runs where
// drill-down is off, so every caller treats "no breakdown" as "show nothing new".

export type BreakdownPart = {
  value: string;
  before: number | null;
  after: number | null;
  change: number | null;
  relative_change: number | null;
  share?: number;
  moved: boolean;
  new: boolean;
  gone: boolean;
};

export type FindingBreakdown = {
  status: 'ok' | 'skipped' | 'failed';
  reason?: string;
  label?: string;
  mode?: 'share' | 'changed_parts';
  spread?: 'concentrated' | 'partial' | 'widespread';
  direction?: 'up' | 'down';
  parts_total?: number;
  parts_changed?: number;
  new_parts?: number;
  top?: BreakdownPart[];
  others?: { count: number; moved: number; share?: number } | null;
};

export function findingBreakdown(finding: Pick<Finding, 'comparison_json'>): FindingBreakdown | null {
  const raw = finding.comparison_json?.breakdown;
  if (!raw || typeof raw !== 'object') return null;
  const breakdown = raw as FindingBreakdown;
  if (!['ok', 'skipped', 'failed'].includes(breakdown.status)) return null;
  return breakdown;
}

function plural(label: string, count: number): string {
  return count === 1 ? label : `${label}s`;
}

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function movedParts(breakdown: FindingBreakdown): BreakdownPart[] {
  return (breakdown.top ?? []).filter((part) => part.moved);
}

/** Short scope label for a chip, e.g. "1 of 6 pods". Null when there's no usable breakdown. */
export function breakdownScopeLabel(breakdown: FindingBreakdown | null): string | null {
  if (!breakdown || breakdown.status !== 'ok' || !breakdown.parts_total) return null;
  const label = breakdown.label ?? 'pod';
  const moved = breakdown.parts_changed ?? 0;
  const newOnly = moved > 0 && movedParts(breakdown).length === moved && movedParts(breakdown).every((part) => part.new);
  if (newOnly) return `${moved} new ${plural(label, moved)}`;
  return `${moved} of ${breakdown.parts_total} ${plural(label, breakdown.parts_total)}`;
}

export function breakdownSpreadColor(breakdown: FindingBreakdown | null): 'error' | 'warning' | 'default' {
  if (!breakdown || breakdown.status !== 'ok') return 'default';
  return breakdown.spread === 'widespread' ? 'warning' : 'error';
}

/** One plain sentence: where the change came from. */
export function breakdownSentence(breakdown: FindingBreakdown): string {
  const label = breakdown.label ?? 'pod';
  const total = breakdown.parts_total ?? 0;
  const moved = movedParts(breakdown);
  const changedCount = breakdown.parts_changed ?? moved.length;
  const verb = breakdown.direction === 'down' ? 'fell' : 'rose';
  const changeWord = breakdown.direction === 'down' ? 'decrease' : 'increase';
  const names = moved.map((part) => part.value).join(', ');

  if (breakdown.spread === 'widespread') {
    const who = changedCount === total ? `All ${total} ${plural(label, total)}` : `${changedCount} of ${total} ${plural(label, total)}`;
    return `${who} ${verb} by a similar amount.`;
  }

  if (breakdown.mode === 'share') {
    const share = moved.reduce((sum, part) => sum + (part.share ?? 0), 0);
    if (breakdown.spread === 'concentrated' && moved[0]) {
      const isNew = moved[0].new ? ` (a new ${label})` : '';
      return `${percent(share)} of the ${changeWord} comes from ${label} ${moved[0].value}${isNew}, 1 of ${total} ${plural(label, total)}.`;
    }
    return `${percent(share)} of the ${changeWord} comes from ${changedCount} of ${total} ${plural(label, total)}: ${names}.`;
  }

  if (breakdown.spread === 'concentrated' && moved[0]) {
    const part = moved[0];
    const from = part.new ? `other ${plural(label, 2)}’ normal level` : formatValue(part.before);
    const others = total - 1;
    return `Only ${label} ${part.value} ${verb} (${from} → ${formatValue(part.after)}). The other ${others} ${plural(label, others)} are unchanged.`;
  }
  return `${changedCount} of ${total} ${plural(label, total)} ${verb}: ${names}.`;
}

/** What the spread usually means for the next step. */
export function breakdownNextStep(breakdown: FindingBreakdown): string {
  const label = breakdown.label ?? 'pod';
  const moved = movedParts(breakdown);
  if (breakdown.spread === 'widespread') {
    return `Not a single bad ${label}. Look at recent code or config changes, or a shared dependency (database, downstream API).`;
  }
  if (moved.length > 0 && moved.every((part) => part.new)) {
    return `These ${plural(label, moved.length)} first appeared after the change started, which looks like a rollout in progress. Compare the new version with the old one before it finishes.`;
  }
  if (breakdown.spread === 'concentrated' && moved[0]) {
    return `Check ${label} ${moved[0].value} and the node it runs on. The other ${plural(label, 2)} look normal, so a rollback is probably not needed.`;
  }
  return `Check what these ${plural(label, moved.length)} have in common, such as node, zone or version.`;
}

const SKIP_REASONS: Record<string, string> = {
  no_change_time: 'this finding has no single moment of change to compare around (for example a slow trend).',
  query_shape_not_supported: 'this metric’s query can’t be split by pod automatically.',
  single_part: 'only one pod or instance reports this metric.',
  too_many_parts: 'there are too many pods to split within the Prometheus series limit.',
  query_failed: 'the per-pod query to Prometheus failed.',
  not_enough_baseline: 'there isn’t enough per-pod data before the change.',
  no_net_change: 'the per-pod data shows no overall change.',
  no_data: 'the per-pod query returned no data.',
  error: 'the drill-down hit an error (see backend logs).',
};

export function breakdownUnavailableReason(breakdown: FindingBreakdown): string {
  return SKIP_REASONS[breakdown.reason ?? ''] ?? 'it could not be computed for this finding.';
}

export function formatValue(value: number | null | undefined): string {
  if (value === null || value === undefined) return '–';
  const magnitude = Math.abs(value);
  if (magnitude === 0) return '0';
  if (magnitude >= 100) return value.toFixed(0);
  if (magnitude >= 1) return value.toFixed(2);
  return value.toPrecision(2);
}
