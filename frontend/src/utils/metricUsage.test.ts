import { describe, expect, it } from 'vitest';
import type { MetricUsageItem } from '../types';
import { jobNames, watchedByTag, watcherLabel, watchQuery } from './metricUsage';

const item = (overrides: Partial<MetricUsageItem>): MetricUsageItem => ({
  metric: 'error_rate', status: 'watched', connections: ['default'], usages: [], via_recording_rules: [],
  problem_findings: 0, latest_finding_id: null, analyzed: true, series: null, ...overrides,
});

describe('watchedByTag', () => {
  it('names the first dashboard and counts alerts', () => {
    const tag = watchedByTag(item({
      usages: [
        { kind: 'dashboard', location: 'Production / API Health / Error rate' },
        { kind: 'dashboard', location: 'Production / API Health / Errors by pod' },
        { kind: 'dashboard', location: 'Team-Lab / Lab Signals / Picked metric' },
        { kind: 'alert_rule', location: 'Production / Checkout error rate high' },
      ],
    }));
    expect(tag).toEqual({
      label: 'On API Health +1 · 1 alert',
      detail: 'Production / API Health / Error rate\nProduction / API Health / Errors by pod\nTeam-Lab / Lab Signals / Picked metric\nAlert: Checkout error rate high',
      watched: true,
    });
  });

  it('says nobody would see a blind spot or unwatched metric', () => {
    expect(watchedByTag(item({ status: 'blind_spot' }))).toMatchObject({ label: 'Not on any dashboard or alert', watched: false });
    expect(watchedByTag(item({ status: 'unwatched' }))).toMatchObject({ watched: false });
  });

  it('explains a metric watched only through a recording rule', () => {
    const tag = watchedByTag(item({ usages: [{ kind: 'recording_rule', location: 'api / job:http:rate5m' }], via_recording_rules: ['job:http:rate5m'] }));
    expect(tag).toEqual({ label: 'Watched via recording rules', detail: 'Read through recording rules: job:http:rate5m', watched: true });
  });

  it('shows nothing for a missing metric', () => {
    expect(watchedByTag(item({ status: 'missing' }))).toBeNull();
  });
});

describe('watcherLabel', () => {
  it('drops the folder from alert rules', () => {
    expect(watcherLabel({ kind: 'alert_rule', location: 'Production / Mock metrics target down' })).toBe('Alert: Mock metrics target down');
    expect(watcherLabel({ kind: 'dashboard', location: 'Production / API Health / Error rate' })).toBe('Production / API Health / Error rate');
  });
});

describe('watchQuery', () => {
  it('picks a query by metric type', () => {
    expect(watchQuery({ metric: 'req_total', metric_type: 'counter' }).query).toBe('sum by (job) (rate(req_total[5m]))');
    expect(watchQuery({ metric: 'lat_bucket', metric_type: 'histogram' }).query).toBe('histogram_quantile(0.95, sum by (le, job) (rate(lat_bucket[5m])))');
    expect(watchQuery({ metric: 'lat_count', metric_type: 'histogram' }).query).toBe('sum by (job) (rate(lat_count[5m]))');
    expect(watchQuery({ metric: 'rpc', metric_type: 'summary' }).query).toBe('max by (job) (rpc{quantile="0.95"})');
    expect(watchQuery({ metric: 'queue_depth', metric_type: 'gauge' }).query).toBe('max by (job) (queue_depth)');
    expect(watchQuery({ metric: 'queue_depth', metric_type: null }).meaning).toBe('current value, highest per job');
  });
});

describe('jobNames', () => {
  it('lists each job once over all connections', () => {
    expect(jobNames({ jobs: { a: { web: 3, api: 2, '': 9 }, b: { web: 1 } } })).toEqual(['api', 'web']);
    expect(jobNames({})).toEqual([]);
  });
});
