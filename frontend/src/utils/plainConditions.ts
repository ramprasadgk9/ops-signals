// Conditions in plain words: "lag is rising" instead of lag.change.upward equals true. A condition
// that fits none of these is still shown, and edited, as the fact the engine reads.

import type { BehaviorConditionInput } from '../types';

export type PlainKind = 'rising' | 'falling' | 'unusual' | 'rose_more' | 'fell_more';

// The analyzers that can produce each fact (backend/app/behavior_intelligence/catalog.py SHAPES).
const CHANGE_ANALYZERS = ['trend', 'baseline_shift', 'ruptures'];
const ANOMALY_ANALYZERS = ['anomaly_zscore', 'pyod_outlier'];

export const PLAIN_KINDS: Array<{ kind: PlainKind; label: string; analyzers: string[] }> = [
  { kind: 'rising', label: 'is rising', analyzers: CHANGE_ANALYZERS },
  { kind: 'falling', label: 'is falling', analyzers: CHANGE_ANALYZERS },
  { kind: 'unusual', label: 'has an unusual spike', analyzers: ANOMALY_ANALYZERS },
  { kind: 'rose_more', label: 'went up by more than', analyzers: CHANGE_ANALYZERS },
  { kind: 'fell_more', label: 'went down by more than', analyzers: CHANGE_ANALYZERS },
];

export type PlainCondition = { alias: string; kind: PlainKind; percent?: number };

const isTrue = (value: unknown) => value === true || value === 'true';

/** The plain reading of a condition, or null when it is written some other way. */
export function parsePlain(row: BehaviorConditionInput): PlainCondition | null {
  const match = /^([^.]+)\.(.+)$/.exec(row.fact);
  if (!match) return null;
  const [, alias, path] = match;
  if (row.operator === 'equals' && isTrue(row.value)) {
    if (path === 'change.upward') return { alias, kind: 'rising' };
    if (path === 'change.downward') return { alias, kind: 'falling' };
    if (path === 'anomaly.present') return { alias, kind: 'unusual' };
  }
  const percent = Number(row.value);
  if (path === 'change.signed_change_percent' && row.value !== '' && Number.isFinite(percent)) {
    if (row.operator === 'greater_than' && percent >= 0) return { alias, kind: 'rose_more', percent };
    if (row.operator === 'less_than' && percent <= 0) return { alias, kind: 'fell_more', percent: -percent };
  }
  return null;
}

/** The condition the engine reads for a plain choice. */
export function toCondition({ alias, kind, percent = 25 }: PlainCondition): BehaviorConditionInput {
  if (kind === 'rising') return { fact: `${alias}.change.upward`, operator: 'equals', value: true };
  if (kind === 'falling') return { fact: `${alias}.change.downward`, operator: 'equals', value: true };
  if (kind === 'unusual') return { fact: `${alias}.anomaly.present`, operator: 'equals', value: true };
  if (kind === 'rose_more') return { fact: `${alias}.change.signed_change_percent`, operator: 'greater_than', value: percent };
  return { fact: `${alias}.change.signed_change_percent`, operator: 'less_than', value: -percent };
}

/** Analyzers an input's list must keep for this choice to ever be true; the first is enough. */
export function analyzersFor(kind: PlainKind): string[] {
  return PLAIN_KINDS.find((item) => item.kind === kind)?.analyzers ?? [];
}

/** "lag is rising", "lag went up by more than 25%", or the fact as written. */
export function describeCondition(row: BehaviorConditionInput): string {
  const plain = parsePlain(row);
  if (!plain) return `${row.fact} ${row.operator} ${String(row.value)}`;
  const label = PLAIN_KINDS.find((item) => item.kind === plain.kind)?.label ?? '';
  return plain.percent === undefined ? `${plain.alias} ${label}` : `${plain.alias} ${label} ${plain.percent}%`;
}
