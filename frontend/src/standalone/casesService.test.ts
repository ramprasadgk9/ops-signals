import { describe, expect, it } from 'vitest';
import { filterCaseRows, groupInvestigationRows, toCaseRow } from './casesService';
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

  it('filters case rows by search, status, and severity', () => {
    const rows = [toCaseRow(makeCase()), toCaseRow(makeCase({ id: 8, case_title: 'Latency spike', case_status: 'resolved' }))];
    expect(filterCaseRows(rows, { search: 'cpu', status: 'open', severity: 'critical' })).toHaveLength(1);
  });

  it('groups investigations from existing case fields', () => {
    const groups = groupInvestigationRows([
      toCaseRow(makeCase()),
      toCaseRow(makeCase({
        id: 8,
        case_status: 'resolved',
        root_cause_status: 'identified',
        finding_snapshot: { ...makeCase().finding_snapshot, health_status: 'normal', importance_score: 0.2, investigation_priority: 0.2 },
      })),
    ]);
    expect(groups.attention).toHaveLength(1);
    expect(groups.all).toHaveLength(2);
  });
});

describe('imported cases', () => {
  const imported = makeCase({ id: 8, finding_id: null, source: 'pagerduty', source_id: 'Q1ABC23', case_status: 'resolved', root_cause_status: 'confirmed' });
  const detected = makeCase();

  it('marks imported rows and never flags them as needing attention', () => {
    const row = toCaseRow(imported);
    expect(row.imported).toBe(true);
    expect(row.source).toBe('pagerduty');
    expect(row.needsAttention).toBe(false);
    expect(toCaseRow(detected).imported).toBe(false);
  });

  it('filters by origin and finds imported cases by their source ID', () => {
    const rows = [toCaseRow(imported), toCaseRow(detected)];
    expect(filterCaseRows(rows, { search: '', status: 'all', severity: 'all', origin: 'imported' }).map((row) => row.id)).toEqual([8]);
    expect(filterCaseRows(rows, { search: '', status: 'all', severity: 'all', origin: 'detected' }).map((row) => row.id)).toEqual([7]);
    expect(filterCaseRows(rows, { search: 'q1abc23', status: 'all', severity: 'all' }).map((row) => row.id)).toEqual([8]);
  });

  it('marks a resolved case whose root cause is not verified, and only that one', () => {
    expect(toCaseRow(makeCase({ case_status: 'resolved', outcome_status: 'resolved', root_cause_verified: false })).rootCauseUnconfirmed).toBe(true);
    expect(toCaseRow(makeCase({ case_status: 'resolved', outcome_status: 'resolved', root_cause_verified: true })).rootCauseUnconfirmed).toBe(false);
    expect(toCaseRow(makeCase({ case_status: 'in_progress', root_cause_verified: false })).rootCauseUnconfirmed).toBe(false);
    expect(toCaseRow(makeCase({ case_status: 'resolved', root_cause_verified: false, source: 'jira' })).rootCauseUnconfirmed).toBe(false);
  });
});
