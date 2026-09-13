import { describe, expect, it } from 'vitest';
import { buildCategoryBreakdown, buildOverviewSummary, isOpenCase } from './overviewModel';
import type { BehaviorFinding, Finding, OperationalCase } from '../types';

function finding(id: number, service: string, category: string): Finding {
  return {
    id,
    service,
    metric_name: 'cpu_usage',
    title: `Finding ${id}`,
    summary: '',
    category,
    health_status: 'critical',
    importance_score: 0.9,
    investigation_priority: 0.9,
    signal_ids: [],
    comparison_json: {},
  };
}

function operationalCase(id: number, findingId: number, status: string, outcomeStatus = 'pending', memoryStatus = 'not_indexed'): OperationalCase {
  return {
    id,
    finding_id: findingId,
    analysis_run_id: 'run-1',
    case_title: `Case ${id}`,
    case_status: status,
    finding_snapshot: finding(findingId, 'payments-api', 'behavior_change'),
    investigation_status: 'in_progress',
    investigation_notes: [],
    root_cause_status: 'unknown',
    root_cause_verified: false,
    outcome_status: outcomeStatus,
    memory_status: memoryStatus,
    created_at: '2026-07-26T00:00:00Z',
    updated_at: '2026-07-26T00:00:00Z',
  };
}

describe('overview model', () => {
  it('defines open cases from lifecycle status', () => {
    expect(isOpenCase(operationalCase(1, 1, 'open'))).toBe(true);
    expect(isOpenCase(operationalCase(2, 2, 'resolved'))).toBe(false);
  });

  it('maps KPI values from real API records', () => {
    const summary = buildOverviewSummary(
      [finding(1, 'payments-api', 'behavior_change'), finding(2, 'checkout-api', 'anomaly')],
      [operationalCase(1, 1, 'resolved', 'resolved', 'indexed')],
      [{ id: 1, title: 'Behavior', summary: '', behavior_id: 'b1', definition_id: 'd1', definition_version: 1, category: 'behavior_change', severity: 'high', input_metrics_json: {}, facts_json: {}, evidence_json: [], matched_conditions_json: [], confidence: 0.8, correlation_json: {}, occurrence_count: 1, last_seen_at: '2026-07-26T00:00:00Z', created_at: '2026-07-26T00:00:00Z' } as BehaviorFinding]
    );

    expect(summary).toEqual({
      activeFindings: 1,
      openCases: 0,
      behaviorChanges: 1,
      impactedServices: 1,
      memoryItems: 1,
    });
  });

  it('aggregates categories without sample fallback data', () => {
    expect(buildCategoryBreakdown([finding(1, 'a', 'trend'), finding(2, 'b', 'trend'), finding(3, 'c', 'anomaly')])).toEqual([
      { category: 'trend', count: 2 },
      { category: 'anomaly', count: 1 },
    ]);
  });
});
