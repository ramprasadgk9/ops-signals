import { describe, expect, it } from 'vitest';
import { filterCaseRows, inCaseTab, toCaseRow } from './casesService';
import type { OperationalCase } from '../types';

function makeCase(overrides: Partial<OperationalCase> = {}): OperationalCase {
  return {
    id: 7,
    finding_id: 3,
    analysis_run_id: 'run-1',
    case_title: 'CPU usage sustained high',
    case_status: 'open',
    finding_snapshot: {
      metric_name: 'cpu_usage',
      service: 'checkout-api',
      title: 'CPU usage sustained high',
      summary: 'CPU pressure stayed above threshold.',
      category: 'behavior_change',
      health_status: 'critical',
      importance_score: 0.9,
      investigation_priority: 0.9,
      signal_ids: [],
      comparison_json: {},
    },
    investigation_status: 'not_started',
    investigation_notes: [],
    root_cause_status: 'unknown',
    root_cause_verified: false,
    outcome_status: 'pending',
    memory_status: 'not_indexed',
    created_at: '2026-07-26T00:00:00Z',
    updated_at: '2026-07-26T01:00:00Z',
    ...overrides,
  };
}

describe('cases service', () => {
  it('normalizes backend cases without inventing owner assignment', () => {
    expect(toCaseRow(makeCase()).assignment).toBe('unsupported');
  });

  it('filters case rows by search and severity', () => {
    const rows = [toCaseRow(makeCase()), toCaseRow(makeCase({ id: 8, case_title: 'Latency spike', finding_snapshot: { ...makeCase().finding_snapshot, title: 'Latency spike', summary: 'Slow.', metric_name: 'latency', health_status: 'normal' } }))];
    expect(filterCaseRows(rows, { search: 'cpu', severity: 'critical' }).map((row) => row.id)).toEqual([7]);
    expect(filterCaseRows(rows, { search: 'latency', severity: 'all' }).map((row) => row.id)).toEqual([8]);
  });

  it('puts each case in the status tabs by where its work stands', () => {
    const notStarted = toCaseRow(makeCase());
    const inProgress = toCaseRow(makeCase({ id: 8, investigation_status: 'in_progress' }));
    const onHold = toCaseRow(makeCase({ id: 9, investigation_status: 'on_hold' }));
    const resolved = toCaseRow(makeCase({ id: 10, case_status: 'resolved', investigation_status: 'completed' }));
    const rows = [notStarted, inProgress, onHold, resolved];
    const ids = (tab: Parameters<typeof inCaseTab>[1]) => rows.filter((row) => inCaseTab(row, tab)).map((row) => row.id);

    expect(rows.map((row) => row.workState)).toEqual(['not_started', 'in_progress', 'on_hold', 'resolved']);
    expect(ids('open')).toEqual([7, 8]);
    expect(ids('in-progress')).toEqual([8]);
    expect(ids('on-hold')).toEqual([9]);
    expect(ids('resolved')).toEqual([10]);
    expect(ids('all')).toEqual([7, 8, 9, 10]);
  });

  it('counts a resolved case as resolved even if its investigation was left on hold', () => {
    const row = toCaseRow(makeCase({ case_status: 'resolved', investigation_status: 'on_hold' }));
    expect(row.workState).toBe('resolved');
    expect(inCaseTab(row, 'on-hold')).toBe(false);
  });
});

describe('imported cases', () => {
  const imported = makeCase({ id: 8, finding_id: null, source: 'pagerduty', source_id: 'Q1ABC23', case_status: 'resolved', root_cause_status: 'confirmed' });
  const detected = makeCase();

  it('marks imported rows', () => {
    const row = toCaseRow(imported);
    expect(row.imported).toBe(true);
    expect(row.source).toBe('pagerduty');
    expect(toCaseRow(detected).imported).toBe(false);
  });

  it('filters by origin and finds imported cases by their source ID', () => {
    const rows = [toCaseRow(imported), toCaseRow(detected)];
    expect(filterCaseRows(rows, { search: '', severity: 'all', origin: 'imported' }).map((row) => row.id)).toEqual([8]);
    expect(filterCaseRows(rows, { search: '', severity: 'all', origin: 'detected' }).map((row) => row.id)).toEqual([7]);
    expect(filterCaseRows(rows, { search: 'q1abc23', severity: 'all' }).map((row) => row.id)).toEqual([8]);
  });

  it('marks a resolved case whose root cause is not verified, and only that one', () => {
    expect(toCaseRow(makeCase({ case_status: 'resolved', outcome_status: 'resolved', root_cause_verified: false })).rootCauseUnconfirmed).toBe(true);
    expect(toCaseRow(makeCase({ case_status: 'resolved', outcome_status: 'resolved', root_cause_verified: true })).rootCauseUnconfirmed).toBe(false);
    expect(toCaseRow(makeCase({ case_status: 'in_progress', root_cause_verified: false })).rootCauseUnconfirmed).toBe(false);
    expect(toCaseRow(makeCase({ case_status: 'resolved', root_cause_verified: false, source: 'jira' })).rootCauseUnconfirmed).toBe(false);
  });
});
