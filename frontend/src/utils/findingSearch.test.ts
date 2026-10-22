import { describe, expect, it } from 'vitest';
import type { Finding } from '../types';
import { findingIdFromQuery, findingSortFromParam, groupRepeatedFindings, searchFindings } from './findingSearch';

function finding(overrides: Partial<Finding>): Finding {
  return {
    metric_name: 'cpu_usage',
    title: 'Something changed',
    summary: '',
    category: 'behavior_change',
    health_status: 'warning',
    importance_score: 0.5,
    investigation_priority: 3,
    signal_ids: [],
    comparison_json: {},
    ...overrides,
  };
}

const checkoutLatency = finding({ id: 57, service: 'checkout', metric_name: 'request_latency_p95', cluster: 'us', importance_score: 0.4, investigation_priority: 2, created_at: '2026-10-04T10:00:00Z' });
const checkoutCpu = finding({ id: 12, service: 'checkout', metric_name: 'cpu_usage', cluster: 'eu', importance_score: 0.9, investigation_priority: 1, created_at: '2026-10-03T10:00:00Z' });
const paymentsErrors = finding({ id: 95, service: 'payments', metric_name: 'error_rate', importance_score: 0.7, investigation_priority: 3, created_at: '2026-10-04T12:00:00Z' });
const all = [checkoutLatency, checkoutCpu, paymentsErrors];
const ids = (findings: Finding[]) => findings.map((item) => item.id);

describe('searchFindings', () => {
  it('matches service, metric and cluster, case-insensitively', () => {
    expect(ids(searchFindings(all, 'Checkout', 'latest'))).toEqual([57, 12]);
    expect(ids(searchFindings(all, 'latency', 'latest'))).toEqual([57]);
    expect(ids(searchFindings(all, 'checkout eu', 'latest'))).toEqual([12]);
  });

  it('finds a finding by number, with or without #', () => {
    expect(ids(searchFindings(all, '#57', 'latest'))).toEqual([57]);
    expect(ids(searchFindings(all, '57', 'latest'))).toEqual([57]);
  });

  it('treats a bare number as text too, but #number as a finding number only', () => {
    expect(ids(searchFindings(all, '95', 'latest'))).toEqual([95, 57]);
    expect(ids(searchFindings(all, '#95', 'latest'))).toEqual([95]);
  });

  it('also matches the extra words given for a finding', () => {
    const extra = (finding: Finding) => (finding.id === 12 ? 'Consumer falling behind consumer_falling_behind' : '');
    expect(ids(searchFindings(all, 'consumer_falling_behind', 'latest', extra))).toEqual([12]);
    expect(ids(searchFindings(all, 'falling checkout', 'latest', extra))).toEqual([12]);
  });

  it('sorts by time, importance or priority', () => {
    expect(ids(searchFindings(all, '', 'latest'))).toEqual([95, 57, 12]);
    expect(ids(searchFindings(all, '', 'oldest'))).toEqual([12, 57, 95]);
    expect(ids(searchFindings(all, '', 'importance'))).toEqual([12, 95, 57]);
    expect(ids(searchFindings(all, '', 'priority'))).toEqual([12, 57, 95]);
  });
});

describe('findingIdFromQuery and findingSortFromParam', () => {
  it('reads a finding number and falls back to latest for unknown sorts', () => {
    expect(findingIdFromQuery(' #57 ')).toBe(57);
    expect(findingIdFromQuery('checkout')).toBeNull();
    expect(findingSortFromParam('importance')).toBe('importance');
    expect(findingSortFromParam('bogus')).toBe('latest');
    expect(findingSortFromParam(null)).toBe('latest');
  });
});

describe('groupRepeatedFindings', () => {
  const run = (id: number, createdAt: string, overrides: Partial<Finding> = {}) =>
    finding({ id, service: 'checkout', metric_name: 'request_latency_p95', cluster: 'eu', connection_id: 'team-a', title: 'Trending up', created_at: createdAt, ...overrides });

  it('shows a repeated finding once, as its first member in sort order, with when it was seen', () => {
    const latest = searchFindings([run(1, '2026-10-04T08:00:00Z'), run(2, '2026-10-04T10:00:00Z'), run(3, '2026-10-04T09:00:00Z')], '', 'latest');
    const [group] = groupRepeatedFindings(latest);

    expect(groupRepeatedFindings(latest)).toHaveLength(1);
    expect(group.finding.id).toBe(2);
    expect(group.runs.map((item) => item.id)).toEqual([2, 3, 1]);
    expect(group.firstSeen).toBe('2026-10-04T08:00:00Z');
    expect(group.lastSeen).toBe('2026-10-04T10:00:00Z');
  });

  it('keeps different clusters, connections, metrics and kinds of change apart', () => {
    const findings = [
      run(1, '2026-10-04T08:00:00Z'),
      run(2, '2026-10-04T08:00:00Z', { cluster: 'us' }),
      run(3, '2026-10-04T08:00:00Z', { connection_id: 'team-b' }),
      run(4, '2026-10-04T08:00:00Z', { metric_name: 'cpu_usage' }),
      run(5, '2026-10-04T08:00:00Z', { title: 'Level shift' }),
    ];
    expect(groupRepeatedFindings(findings)).toHaveLength(5);
  });

  it('groups by the problem the backend linked, so the same kind of problem at another time stays apart', () => {
    const timed = { event_start: '2026-10-12T09:00:00Z', event_end: '2026-10-12T09:45:00Z' };
    const findings = [
      run(1, '2026-10-12T09:10:00Z', { ...timed, problem_id: null }),
      run(2, '2026-10-12T09:20:00Z', { ...timed, problem_id: 1 }),
      run(3, '2026-10-12T14:10:00Z', { event_start: '2026-10-12T14:00:00Z', event_end: '2026-10-12T14:10:00Z', problem_id: null }),
    ];

    const groups = groupRepeatedFindings(findings);

    expect(groups.map((group) => group.runs.map((item) => item.id))).toEqual([[1, 2], [3]]);
    expect(groups[0].latest?.id).toBe(2);
  });

  it('keeps the list order and lists every run when grouping is off', () => {
    const findings = [run(1, '2026-10-04T10:00:00Z'), run(2, '2026-10-04T09:00:00Z', { cluster: 'us' }), run(3, '2026-10-04T08:00:00Z')];
    expect(groupRepeatedFindings(findings).map((group) => group.finding.id)).toEqual([1, 2]);
    expect(groupRepeatedFindings(findings, false).map((group) => group.finding.id)).toEqual([1, 2, 3]);
  });
});
