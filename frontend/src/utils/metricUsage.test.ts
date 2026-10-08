import { describe, expect, it } from 'vitest';
import type { MetricUsageItem } from '../types';
import { watchedByTag, watcherLabel } from './metricUsage';

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
