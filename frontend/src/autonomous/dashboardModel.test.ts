import { describe, expect, it } from 'vitest';
import type { AnalysisRun, Finding, OperationalCase } from '../types';
import { buildAutonomousDashboardData, type AutonomousPolicyRun } from './dashboardModel';
import type { AutonomousRunResponse } from '../grafana/contracts';

function finding(overrides: Partial<Finding> = {}): Finding {
  return {
    id: 1,
    service: 'checkout',
    metric_name: 'latency',
    title: 'Latency changed',
    summary: '',
    category: 'behavior_change',
    health_status: 'significant',
    importance_score: 0.7,
    investigation_priority: 2,
    signal_ids: [],
    comparison_json: {},
    created_at: '2026-08-13T17:20:00Z',
    ...overrides,
  };
}

function operationalCase(overrides: Partial<OperationalCase> = {}): OperationalCase {
  return {
    id: 12,
    finding_id: 1,
    analysis_run_id: 'run-1',
    case_title: 'checkout latency degradation',
    case_status: 'open',
    finding_snapshot: finding({ service: 'checkout', metric_name: 'latency' }),
    investigation_status: 'not_started',
    investigation_notes: [],
    root_cause_status: 'unknown',
    root_cause_verified: false,
    outcome_status: 'pending',
    memory_status: 'not_indexed',
    created_at: '2026-08-13T17:22:00Z',
    updated_at: '2026-08-13T17:23:00Z',
    ...overrides,
  };
}

function policyRun(overrides: Partial<AutonomousPolicyRun> = {}): AutonomousPolicyRun {
  return {
    id: 'policy-run-1',
    status: 'completed',
    metrics_discovered: 12456,
    metrics_selected: 328,
    jobs_planned: 328,
    jobs_completed: 320,
    jobs_skipped: 8,
    jobs_failed: 0,
    completed_at: '2026-08-13T17:23:00Z',
    ...overrides,
  };
}

function runResult(overrides: Partial<AutonomousRunResponse> = {}): AutonomousRunResponse {
  return {
    status: 'completed',
    planned_jobs: 1,
    executed_jobs: 1,
    skipped_jobs: 0,
    failed_jobs: 0,
    analysis_window: '6h',
    requested_start: '2026-08-13T11:00:00Z',
    requested_end: '2026-08-13T17:00:00Z',
    step: '10m',
    preview: {
      scope_summary: { services: 1, namespaces: 0, label_mapping: {}, selector: '{}' },
      monitoring_summary: { categories: ['capacity'], concepts: ['cpu'] },
      metrics_discovered: 4,
      metrics_selected: 1,
      metrics_matched: 1,
      metrics_excluded: 3,
      planned_jobs: 1,
      budget_limited_jobs: 0,
      budget_limited: 0,
      warnings: [],
      items: [],
    },
    results: [{
      metric_name: 'cpu_usage',
      service: 'spike-lab',
      promql: 'avg by (service) (cpu_usage{service="spike-lab"})',
      status: 'completed',
      analysis_run_id: 'current-run',
      sample_count: 12,
      series_count: 1,
      signal_count: 1,
      findings_count: 1,
      behavior_findings_count: 0,
      warnings: [],
    }],
    warnings: [],
    ...overrides,
  };
}

describe('autonomous dashboard model', () => {
  it('maps policy run counts into discovery and execution summaries', () => {
    const data = buildAutonomousDashboardData({
      findings: [finding()],
      cases: [operationalCase()],
      analysisRuns: [],
      policyRuns: [policyRun()],
    });

    expect(data.summary.metricsDiscovered).toBe(12456);
    expect(data.summary.candidatesSelected).toBe(328);
    expect(data.summary.executed).toBe(320);
    expect(data.summary.skipped).toBe(8);
    expect(data.summary.failed).toBe(0);
  });

  it('falls back to unavailable discovery values when policy data is absent', () => {
    const data = buildAutonomousDashboardData({
      findings: [],
      cases: [],
      analysisRuns: [],
      policyRuns: [],
    });

    expect(data.summary.metricsDiscovered).toBeNull();
    expect(data.summary.candidatesSelected).toBeNull();
    expect(data.selection.title).toBe('Metric Selection');
    expect(data.selection.screeningEnabled).toBe(false);
  });

  it('does not label metadata selection as statistical candidate screening', () => {
    const data = buildAutonomousDashboardData({
      findings: [],
      cases: [],
      analysisRuns: [],
      policyRuns: [policyRun()],
    });

    expect(data.selection.selectedLabel).toBe('Selected by monitoring policy');
    expect(data.selection.reasons).toEqual([]);
  });

  it('sorts top findings by importance score', () => {
    const data = buildAutonomousDashboardData({
      findings: [
        finding({ id: 1, metric_name: 'cpu_usage', importance_score: 0.64 }),
        finding({ id: 2, metric_name: 'error_rate', importance_score: 0.91 }),
      ],
      cases: [],
      analysisRuns: [],
    });

    expect(data.topFindings.map((row) => row.metric)).toEqual(['error_rate', 'cpu_usage']);
  });

  it('groups behavior distribution by existing finding category', () => {
    const data = buildAutonomousDashboardData({
      findings: [
        finding({ id: 1, category: 'behavior_change' }),
        finding({ id: 2, category: 'behavior_change' }),
        finding({ id: 3, category: 'unusual_activity' }),
      ],
      cases: [],
      analysisRuns: [],
    });

    expect(data.behaviorDistribution).toEqual([
      { label: 'Behavior Change', count: 2 },
      { label: 'Unusual Activity', count: 1 },
    ]);
  });

  it('builds compact execution rows from policy runs or analysis runs', () => {
    const fromPolicy = buildAutonomousDashboardData({
      findings: [],
      cases: [],
      analysisRuns: [],
      policyRuns: [policyRun({ jobs_completed: 7 })],
    });
    expect(fromPolicy.executionRows[0].metrics).toBe('7 metrics');

    const fromRuns = buildAutonomousDashboardData({
      findings: [],
      cases: [],
      policyRuns: [],
      analysisRuns: [{ id: 'run-1', source_type: 'prometheus', provider: 'prometheus', service: 'checkout', metric_name: 'cpu_usage', start_time: '', end_time: '', sample_count: 31, status: 'completed', created_at: '' } as AnalysisRun],
    });
    expect(fromRuns.executionRows[0].scope).toBe('checkout / cpu_usage');
    expect(fromRuns.executionRows[0].metrics).toBe('31 samples');
  });

  it('scopes findings and cases to the current run when run results include analysis run ids', () => {
    const data = buildAutonomousDashboardData({
      findings: [
        finding({ id: 1, metric_name: 'cpu_usage', analysis_run_id: 'current-run' }),
        finding({ id: 2, metric_name: 'error_rate', analysis_run_id: 'old-run' }),
      ],
      cases: [
        operationalCase({ id: 1, analysis_run_id: 'current-run', case_title: 'current case' }),
        operationalCase({ id: 2, analysis_run_id: 'old-run', case_title: 'old case' }),
      ],
      analysisRuns: [],
      policyRuns: [policyRun()],
      runResult: runResult(),
    });

    expect(data.summary.findingsGenerated).toBe(1);
    expect(data.topFindings.map((row) => row.metric)).toEqual(['cpu_usage']);
    expect(data.recentCases.map((row) => row.title)).toEqual(['Case #1 - current case']);
    expect(data.casesScope).toBe('current_run');
    expect(data.executionRows[0].current).toBe(true);
  });
});
