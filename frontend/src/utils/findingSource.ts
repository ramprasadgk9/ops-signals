/** Where a finding's data came from (FindingOut.source), in words for the card and drawer. */
const LABELS: Record<string, string> = { prometheus: 'Prometheus', otlp: 'OTLP', csv: 'CSV upload' };

export function findingSourceLabel(source?: string | null): string | null {
  if (!source) return null;
  return LABELS[source] ?? source;
}

/** Why a finding has no per-pod breakdown because of where its data came from, or null when the
 * source supports it (drill-down re-runs the Prometheus query grouped by pod). */
export function breakdownMissingForSource(source?: string | null): string | null {
  if (!source || source === 'prometheus') return null;
  return `Breakdown by pod isn't available for ${findingSourceLabel(source)} data yet: it re-runs the query by pod, which needs a Prometheus-compatible source.`;
}
