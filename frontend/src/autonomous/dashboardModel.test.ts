import { describe, expect, it } from 'vitest';
import type { AnalysisRun, Finding, OperationalCase } from '../types';
import { buildAutonomousDashboardData, formatMatchedRule, type AutonomousPolicyRun } from './dashboardModel';
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
    expect(data.selection.reasonsAvailable).toBe(false);
  });

  it('groups excluded preview items into an actionable why-excluded breakdown', () => {
    const preview = runResult().preview;
    preview.items = [
      { metric_name: 'cpu_usage', service: 'checkout', namespace: 'commerce', planned: true, exclusion_reason: null, transformation: 'raw', aggregation: 'avg', group_by: [], promql: '', confidence: 1, aggregation_strategy: 'avg', estimated_series_count: 1, analysis_window: '24h' },
      { metric_name: 'container_cpu_usage_seconds_total', service: 'payments', namespace: 'commerce', environment: 'production', category: 'capacity', concept: 'cpu', planned: true, exclusion_reason: null, transformation: 'raw', aggregation: 'avg', group_by: [], promql: '', confidence: 1, aggregation_strategy: 'avg', estimated_series_count: 1, analysis_window: '24h' },
      { metric_name: 'container_cpu_usage', service: 'payments', namespace: 'commerce', planned: false, exclusion_reason: 'category_disabled', would_be_category: ['capacity'], transformation: 'raw', aggregation: 'avg', group_by: [], promql: '', confidence: 0, aggregation_strategy: 'avg', estimated_series_count: 1, analysis_window: '24h' },
      { metric_name: 'node_cpu_usage', service: 'payments', namespace: 'commerce', planned: false, exclusion_reason: 'category_disabled', would_be_category: ['capacity', 'infrastructure'], transformation: 'raw', aggregation: 'avg', group_by: [], promql: '', confidence: 0, aggregation_strategy: 'avg', estimated_series_count: 1, analysis_window: '24h' },
      { metric_name: 'build_info', service: null, namespace: null, planned: false, exclusion_reason: 'static_metadata_metric', matched_rule: 'static.suffix._info', transformation: 'raw', aggregation: 'avg', group_by: [], promql: '', confidence: 0, aggregation_strategy: 'avg', estimated_series_count: 1, analysis_window: '24h' },
      { metric_name: 'http_requests_created', service: null, namespace: null, planned: false, exclusion_reason: 'created_timestamp', transformation: 'raw', aggregation: 'avg', group_by: [], promql: '', confidence: 0, aggregation_strategy: 'avg', estimated_series_count: 1, analysis_window: '24h' },
      { metric_name: 'totally_unknown_metric', service: 'checkout', namespace: 'commerce', planned: false, exclusion_reason: 'no_matching_rule', transformation: 'raw', aggregation: 'avg', group_by: [], promql: '', confidence: 0, aggregation_strategy: 'avg', estimated_series_count: 1, analysis_window: '24h' },
      { metric_name: 'cpu_usage_dup', service: 'payments', namespace: 'commerce', environment: 'production', category: 'capacity', concept: 'cpu', planned: false, exclusion_reason: 'duplicate_lower_rank', would_be_category: ['capacity'], transformation: 'raw', aggregation: 'avg', group_by: [], promql: '', confidence: 0, aggregation_strategy: 'avg', estimated_series_count: 1, analysis_window: '24h' },
    ];

    const data = buildAutonomousDashboardData({
      findings: [],
      cases: [],
      analysisRuns: [],
      policyRuns: [],
      previewResult: preview,
    });

    expect(data.selection.reasonsAvailable).toBe(true);
    const byLabel = Object.fromEntries(data.selection.reasons.map((entry) => [entry.label, entry]));

    expect(byLabel['Category not enabled'].count).toBe(2);
    expect(byLabel['Category not enabled'].actionable).toBe(true);
    expect(byLabel['Category not enabled'].wouldEnableCategories).toEqual(
      expect.arrayContaining([{ category: 'capacity', count: 2 }, { category: 'infrastructure', count: 1 }]),
    );

    expect(byLabel['System/internal metric'].count).toBe(2);
    expect(byLabel['System/internal metric'].actionable).toBe(false);
    // The exact matched rule (e.g. which suffix/pattern) is shown per metric, not just the bucket label.
    expect(byLabel['System/internal metric'].metrics.find((m) => m.metricName === 'build_info')?.matchedRule).toBe('static.suffix._info');

    expect(byLabel['No rule recognizes this metric'].count).toBe(1);
    expect(byLabel['No rule recognizes this metric'].actionable).toBe(false);
    expect(byLabel['No rule recognizes this metric'].wouldEnableCategories).toBeUndefined();

    // A duplicate-rank exclusion can carry a would_be_category too (the metric matched a
    // category fine, it just lost to a higher-ranked duplicate) - that category is likely
    // already enabled, so it must never surface an "Enable" action here.
    expect(byLabel['Duplicate of a higher-confidence metric'].count).toBe(1);
    expect(byLabel['Duplicate of a higher-confidence metric'].actionable).toBe(false);
    expect(byLabel['Duplicate of a higher-confidence metric'].wouldEnableCategories).toBeUndefined();
    // Names exactly which planned metric won the same (service, category, concept) slot.
    expect(byLabel['Duplicate of a higher-confidence metric'].metrics[0].supersededByMetric).toBe('container_cpu_usage_seconds_total');

    // The planned item never shows up in any exclusion bucket.
    const allBucketedMetrics = data.selection.reasons.flatMap((entry) => entry.metrics.map((metric) => metric.metricName));
    expect(allBucketedMetrics).not.toContain('cpu_usage');
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

  it('formats execution row with budget-excluded count when run is budget limited', () => {
    const data = buildAutonomousDashboardData({
      findings: [],
      cases: [],
      analysisRuns: [],
      runResult: runResult({
        planned_jobs: 50,
        executed_jobs: 50,
        budget_limited_jobs: 250,
        budget_excluded_metrics_count: 250,
        budget_excluded_metrics: ['metric_1', 'metric_2'],
      }),
    });

    expect(data.executionRows[0].metrics).toBe('50 executed / 50 planned (250 budget-excluded)');
  });

  it('formats historical policy run row with budget-excluded count when historical run was budget limited', () => {
    const data = buildAutonomousDashboardData({
      findings: [],
      cases: [],
      analysisRuns: [],
      policyRuns: [
        policyRun({
          jobs_completed: 100,
          budget_limited_jobs: 400,
        }),
      ],
    });

    expect(data.executionRows[0].metrics).toBe('100 metrics (400 budget-excluded)');
  });

  it('carries the not-checked count from the latest policy run to the summary and its row', () => {
    const data = buildAutonomousDashboardData({
      findings: [],
      cases: [],
      analysisRuns: [],
      policyRuns: [policyRun({ jobs_completed: 33, jobs_not_checked: 33 })],
    });

    expect(data.summary.notChecked).toBe(33);
    expect(data.executionRows[0].notChecked).toBe(33);
  });

  it('takes the not-checked count from a run just started here', () => {
    const data = buildAutonomousDashboardData({
      findings: [],
      cases: [],
      analysisRuns: [],
      runResult: runResult({ not_checked_jobs: 1 }),
    });

    expect(data.summary.notChecked).toBe(1);
    expect(data.executionRows[0].notChecked).toBe(1);
  });

  it('links each top finding to that finding on the Findings page', () => {
    const data = buildAutonomousDashboardData({ findings: [finding({ id: 12105 })], cases: [], analysisRuns: [] });

    expect(data.topFindings[0].href).toBe('/findings?finding=12105');
  });

  it('names the first two services of a run and how many more it covered', () => {
    const many = buildAutonomousDashboardData({
      findings: [],
      cases: [],
      analysisRuns: [],
      policyRuns: [policyRun({ policy_snapshot: { scope_summary: { services_resolved: ['checkout', 'drift-lab', 'payments', 'spike-lab'] } } })],
    });
    const two = buildAutonomousDashboardData({
      findings: [],
      cases: [],
      analysisRuns: [],
      policyRuns: [policyRun({ policy_snapshot: { scope_summary: { services_resolved: ['checkout', 'drift-lab'] } } })],
    });

    expect(many.executionRows[0].scope).toBe('checkout, drift-lab + 2 more');
    expect(two.executionRows[0].scope).toBe('checkout, drift-lab');
  });

  it('keeps not-checked unknown for runs saved before it was counted', () => {
    const data = buildAutonomousDashboardData({
      findings: [],
      cases: [],
      analysisRuns: [],
      policyRuns: [policyRun()],
    });

    expect(data.summary.notChecked).toBeNull();
    expect(data.executionRows[0].notChecked).toBeNull();
  });
});

describe('formatMatchedRule', () => {
  it('turns internal matched_rule ids into plain-language detail', () => {
    expect(formatMatchedRule('custom.exclude.custom_ignore_.*')).toBe('matched your exclude pattern "custom_ignore_.*"');
    expect(formatMatchedRule('static.suffix._info')).toBe('name ends with "_info"');
    expect(formatMatchedRule('static.exact.prometheus_build_info')).toBe('blocklisted metric name');
    // The pattern value itself contains dots (a real regex from prometheus_metric_knowledge.yaml) -
    // this must not get mangled by treating every dot as a structural separator.
    expect(formatMatchedRule('static.pattern..*build.*info.*')).toBe('matched system pattern ".*build.*info.*"');
    expect(formatMatchedRule(null)).toBeNull();
    expect(formatMatchedRule(undefined)).toBeNull();
  });
});
