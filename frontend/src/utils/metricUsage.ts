import type { MetricUsageItem, MetricUsageStatus, MetricUsageWatcher } from '../types';

export const METRIC_USAGE_STATUSES: Record<MetricUsageStatus, { label: string; color: string; hint: string }> = {
  blind_spot: { label: 'Blind spot', color: '#d03b3b', hint: 'Ops Signals found problems, but no dashboard or alert shows this metric' },
  missing: { label: 'Missing', color: '#f97316', hint: 'A dashboard or alert reads this metric, but Prometheus has no such metric: an empty panel' },
  watched: { label: 'Watched', color: '#0ca30c', hint: 'On a dashboard panel or used by an alert' },
  unwatched: { label: 'Not watched', color: 'var(--os-muted)', hint: 'No dashboard or alert reads it, and nothing is wrong with it' },
};

/** "Production / API Health / Error rate" -> "Production / API Health": the dashboard, without the panel. */
export function dashboardName(watcher: MetricUsageWatcher): string {
  return watcher.location.split(' / ').slice(0, 2).join(' / ');
}

/** What a person sees for one watcher: a dashboard (by name) or an alert rule (by title). */
export function watcherLabel(watcher: MetricUsageWatcher): string {
  if (watcher.kind === 'alert_rule') return `Alert: ${watcher.location.split(' / ').slice(1).join(' / ') || watcher.location}`;
  if (watcher.kind === 'recording_rule') return `Recording rule: ${watcher.location}`;
  return watcher.location;
}

/** Watchers that mean a person would see the metric: dashboards and alerts, not recording rules. */
export function visibleWatchers(item: MetricUsageItem): MetricUsageWatcher[] {
  return item.usages.filter((usage) => usage.kind !== 'recording_rule');
}

/** Short tag for a finding's metric: who would see a problem on it, or that nobody would. */
export function watchedByTag(item: MetricUsageItem): { label: string; detail: string; watched: boolean } | null {
  if (item.status === 'missing') return null;
  const watchers = visibleWatchers(item);
  if (item.status !== 'watched') {
    return {
      label: 'Not on any dashboard or alert',
      detail: 'Only Ops Signals sees problems on this metric. Add a panel or an alert for it in Grafana.',
      watched: false,
    };
  }
  const dashboards = [...new Set(watchers.filter((usage) => usage.kind === 'dashboard').map(dashboardName))];
  const alerts = watchers.filter((usage) => usage.kind === 'alert_rule').length;
  const parts = [
    dashboards.length ? `On ${dashboards[0].split(' / ').pop()}${dashboards.length > 1 ? ` +${dashboards.length - 1}` : ''}` : null,
    alerts ? `${alerts} ${alerts === 1 ? 'alert' : 'alerts'}` : null,
  ].filter(Boolean);
  const detail = watchers.length
    ? watchers.map(watcherLabel).join('\n')
    : `Read through recording rules: ${item.via_recording_rules.join(', ')}`;
  return { label: parts.join(' · ') || 'Watched via recording rules', detail, watched: true };
}

/** A query to put on a panel or alert for an unwatched metric, by its type: a rate for counters,
 * the p95 for histogram buckets, the value for anything else. */
export function watchQuery(item: Pick<MetricUsageItem, 'metric' | 'metric_type'>): { query: string; meaning: string } {
  const { metric } = item;
  const histogram = item.metric_type === 'histogram' || item.metric_type === 'gaugehistogram';
  if (histogram && metric.endsWith('_bucket')) {
    return { query: `histogram_quantile(0.95, sum by (le, job) (rate(${metric}[5m])))`, meaning: '95th percentile, per job' };
  }
  if (item.metric_type === 'counter' || ((histogram || item.metric_type === 'summary') && /_(sum|count)$/.test(metric))) {
    return { query: `sum by (job) (rate(${metric}[5m]))`, meaning: 'per second, per job' };
  }
  if (item.metric_type === 'summary') {
    return { query: `max by (job) (${metric}{quantile="0.95"})`, meaning: '95th percentile, per job' };
  }
  return { query: `max by (job) (${metric})`, meaning: 'current value, highest per job' };
}

/** The job labels of a metric's series over all connections, without the unlabelled ones. */
export function jobNames(item: Pick<MetricUsageItem, 'jobs'>): string[] {
  return [...new Set(Object.values(item.jobs ?? {}).flatMap((byJob) => Object.keys(byJob)).filter(Boolean))].sort();
}
