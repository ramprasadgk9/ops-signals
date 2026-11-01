// "Which analyzer fits my metric?": the metric list, how router ratings group into plain columns,
// and the per-service setting offered for analyzers that run on a metric they don't suit.
import type { AnalyzerRecommendation, MetricSample } from '../types';

export type DiscoveredMetric = {
  key: string;
  service: string;
  metric_name: string;
  analysis_run_id: string | null;
  sample_count: number;
  start_time: string;
  end_time: string;
};

/** One entry per service and metric, from its newest run (the sample list is newest first). */
export function discoveredMetrics(samples: MetricSample[]): DiscoveredMetric[] {
  const seen = new Map<string, DiscoveredMetric>();
  for (const sample of samples) {
    const key = `${sample.service}::${sample.metric_name}`;
    if (seen.has(key)) continue;
    seen.set(key, {
      key,
      service: sample.service,
      metric_name: sample.metric_name,
      analysis_run_id: sample.analysis_run_id ?? null,
      sample_count: sample.sample_count,
      start_time: sample.start_time,
      end_time: sample.end_time,
    });
  }
  return Array.from(seen.values());
}

export type FitGroup = 'good' | 'can_help' | 'not_a_fit';

export const FIT_GROUPS: { id: FitGroup; title: string; empty: string }[] = [
  { id: 'good', title: 'Good fit', empty: 'No analyzer is a clear fit for this data.' },
  { id: 'can_help', title: 'Can help', empty: 'None.' },
  { id: 'not_a_fit', title: 'Not a fit', empty: 'None.' },
];

/** The router says recommended / optional / not_recommended, and also rejected or overridden;
 * the older scorers say conditional. Every value lands in a column, so none is dropped. */
export function fitGroup(recommendation: string): FitGroup {
  if (recommendation === 'recommended') return 'good';
  if (recommendation === 'optional' || recommendation === 'conditional') return 'can_help';
  return 'not_a_fit';
}

export const LAST_RUN_LABEL: Record<'ran' | 'skipped' | 'failed', string> = {
  ran: 'Ran last time',
  skipped: "Didn't run last time",
  failed: 'Failed last time',
};

/** Analyzers that ran on this metric although they don't suit it: the only ones worth turning off. */
export function ranButNotAFit(recommendations: AnalyzerRecommendation[]): AnalyzerRecommendation[] {
  return recommendations.filter((item) => item.available !== false && fitGroup(item.recommendation) === 'not_a_fit' && item.last_run === 'ran');
}

/** A per-service override (config/analyzer_overrides.d/) that stops these analyzers on this metric.
 * Overrides can turn analyzers off or tune them, never turn one on: the router decides what runs. */
export function turnOffSnippet(service: string, metric: string, analyzerIds: string[]): string {
  const name = `${service}_${metric}`.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'this_metric';
  return [
    '# Save in config/analyzer_overrides.d/ as a .yml file. Read at the start of every run; no restart.',
    'overrides:',
    `  ${name}:`,
    '    scope:',
    `      service: ${JSON.stringify(service)}`,
    `      metric: ${JSON.stringify(metric)}`,
    '    reason: These analyzers ran here but do not suit this metric\'s data.',
    '    selection:',
    `      disabled: [${analyzerIds.join(', ')}]`,
    '',
  ].join('\n');
}
