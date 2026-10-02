import type { Signal } from '../types';

export type SignalGroup = {
  key: string;
  label: string;
  count: number;
  signals: Signal[];
};

const MAX_TOOLTIP_SIGNALS = 3;

/**
 * The finding's signals that count as evidence, in signal_ids order. Skips low-severity signals and
 * diagnostic ones: analyzers gated by a finding rule still emit a signal when the rule didn't match
 * (evidence.finding_rule_matched === false), and that signal is not a detection.
 */
export function supportingSignals(signalIds: string[], signals: Signal[]): Signal[] {
  const byId = new Map(signals.map((signal) => [signal.id, signal]));
  return signalIds
    .map((signalId) => byId.get(signalId))
    .filter((signal): signal is Signal => Boolean(signal))
    .filter((signal) => signal.evidence?.finding_rule_matched !== false)
    .filter((signal) => signal.severity ? signal.severity.toLowerCase() !== 'low' : signal.importance_score >= 0.55);
}

/**
 * Groups signals by analyzer (falling back to signal_type) so a finding with e.g. 30
 * pyod_outlier hits renders as one "pyod_outlier x30" chip instead of 30 identical ones.
 * Preserves first-seen order of each analyzer/signal_type across the input list.
 */
export function groupSignalsByAnalyzer(signals: Signal[]): SignalGroup[] {
  const order: string[] = [];
  const groups = new Map<string, Signal[]>();
  for (const signal of signals) {
    const key = signal.analyzer_id ?? signal.signal_type;
    if (!groups.has(key)) {
      groups.set(key, []);
      order.push(key);
    }
    groups.get(key)!.push(signal);
  }
  return order.map((key) => {
    const groupSignals = groups.get(key)!;
    return { key, label: key, count: groupSignals.length, signals: groupSignals };
  });
}

function formatEvidenceSummary(signal: Signal): string {
  const evidenceKeys = Object.keys(signal.evidence ?? {});
  if (evidenceKeys.length === 0) return 'No evidence details available.';
  return evidenceKeys
    .slice(0, 3)
    .map((key) => `${key}: ${typeof signal.evidence[key] === 'object' ? JSON.stringify(signal.evidence[key]) : String(signal.evidence[key])}`)
    .join('\n');
}

function formatSignalLine(signal: Signal): string {
  const window = signal.start_time
    ? `${new Date(signal.start_time).toLocaleString()}${
        signal.end_time && signal.end_time !== signal.start_time ? ` → ${new Date(signal.end_time).toLocaleString()}` : ''
      }`
    : null;
  return [signal.severity?.toUpperCase(), window, signal.summary].filter(Boolean).join(' · ');
}

/** Tooltip for a single, ungrouped signal - unchanged from the original per-signal behavior. */
export function singleSignalTooltip(signal: Signal): string {
  return `${signal.analyzer_id ?? signal.signal_type}\n${signal.summary ?? 'No summary available.'}\n\nEvidence:\n${formatEvidenceSummary(signal)}`;
}

/** Tooltip for a signal group: same as singleSignalTooltip when there's only one signal,
 *  otherwise a condensed multi-signal summary (first few, then a "+N more" line). */
export function signalGroupTooltip(group: SignalGroup): string {
  if (group.count === 1) return singleSignalTooltip(group.signals[0]);
  const shown = group.signals.slice(0, MAX_TOOLTIP_SIGNALS).map(formatSignalLine).join('\n');
  const remaining = group.count - Math.min(group.count, MAX_TOOLTIP_SIGNALS);
  return `${group.label} — ${group.count} signals\n\n${shown}${remaining > 0 ? `\n+${remaining} more not shown` : ''}`;
}

export function signalGroupChipLabel(group: SignalGroup): string {
  return group.count > 1 ? `${group.label} ×${group.count}` : group.label;
}
