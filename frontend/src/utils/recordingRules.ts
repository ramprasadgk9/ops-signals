import type { RecordingRule, RecordingRuleAlert } from '../types';

// Shown on the tag in the Metrics list, in both builds.
export const RECORDING_RULE_TOOLTIP = 'Prometheus saves the result of a query under this name. Pick it to see the query.';

/** Rules by the metric name they save to. A name saved by two groups keeps the first. */
export function recordingRulesByName(rules: RecordingRule[] | undefined): Map<string, RecordingRule> {
  const byName = new Map<string, RecordingRule>();
  for (const rule of rules ?? []) {
    if (!byName.has(rule.name)) byName.set(rule.name, rule);
  }
  return byName;
}

/** "every 15s", "every 1m", "every 1m30s" - or "on a schedule" when the interval isn't known. */
export function ruleSchedule(rule: RecordingRule): string {
  const seconds = Math.round(rule.interval_seconds ?? 0);
  if (seconds <= 0) return 'on a schedule';
  if (seconds < 60) return `every ${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `every ${minutes}m${rest ? `${rest}s` : ''}`;
}

// A rule that adds up every service saves a result with no service label. Findings are always saved
// under one service, so such a rule can be previewed but not analyzed.
export const NO_SERVICE_LABEL_NOTE = "This rule adds up all services, so its result doesn't belong to one service and can't be saved as a finding. Preview still works. To analyze it per service, the rule has to keep the label, for example sum by (service) (...).";

/** "Used by alert X (fires above 5 for 5 minutes): <the alert's own words>" for the note under the
 * PromQL box, so the number's meaning is clear before anything runs. */
export function ruleAlertSentence(alert: RecordingRuleAlert): string {
  const when = alert.fires ? ` (fires ${alert.fires}${alert.wait ? ` for ${alert.wait}` : ''})` : '';
  return `Used by alert ${alert.name}${when}${alert.text ? `: ${alert.text}` : '.'}`;
}

/** The first sentence of the note under the PromQL box. */
export function ruleNoteLead(rule: RecordingRule): string {
  const group = rule.group ? ` in group ${rule.group}` : '';
  if (rule.health === 'err') return `Recording rule${group}. Its last run failed, so recent points may be missing.`;
  if (rule.health === 'unknown') return `Recording rule${group}. Prometheus hasn't run it yet; it saves this query's result under this name:`;
  return `Recording rule${group}. Prometheus runs this query ${ruleSchedule(rule)} and saves the result under this name:`;
}

const SIMPLE_SELECTOR = /^\s*([a-zA-Z_:][a-zA-Z0-9_:]*)\s*(\{[^}]*\})?\s*$/;

/** The metric a plain selector such as `name{service="x"}` reads; null for any other query. */
export function selectorMetricName(promql: string | null | undefined): string | null {
  const match = SIMPLE_SELECTOR.exec(promql ?? '');
  return match ? match[1] : null;
}

/** The rule behind a run: its metric name, or the plain selector it queried. */
export function ruleForRun(
  byName: Map<string, RecordingRule>,
  metricName: string | null | undefined,
  promql: string | null | undefined,
): RecordingRule | null {
  return (metricName ? byName.get(metricName) : undefined) ?? byName.get(selectorMetricName(promql) ?? '') ?? null;
}

/** A selector for the series of these metrics that lack `label`: Prometheus matches `label=""` on
 * series without it. Asking for their names says which rules a `{service="..."}` query can't find. */
export function missingLabelSelector(names: string[], label: string): string | null {
  const valid = names.filter((name) => /^[a-zA-Z_:][a-zA-Z0-9_:]*$/.test(name));
  if (!valid.length || !/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(label)) return null;
  return `{__name__=~"${valid.join('|')}",${label}=""}`;
}
