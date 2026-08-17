import type { AnalysisRun, BehaviorFinding, Finding } from '../types';
import type { AutonomousPreviewResponse, AutonomousRunResponse } from '../grafana/contracts';

export type AutonomousPolicyRun = {
  id: string;
  policy_run_id?: string;
  policy_id?: string | null;
  trigger?: string | null;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
  policy_snapshot?: Record<string, unknown> | null;
  metrics_discovered?: number | null;
  metrics_selected?: number | null;
  jobs_planned?: number | null;
  jobs_completed?: number | null;
  jobs_skipped?: number | null;
  jobs_failed?: number | null;
  findings_created?: number | null;
  error_summary?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type AutonomousSelectionSummary = {
  title: string;
  discovered: number | null;
  selected: number | null;
  excluded: number | null;
  reductionPercent: number | null;
  selectedLabel: string;
  screeningEnabled: boolean;
  reasons: Array<{ label: string; count: number }>;
};

export type AutonomousDashboardSummary = {
  metricsDiscovered: number | null;
  candidatesSelected: number | null;
  findingsGenerated: number;
  casesOpen: number;
  executed: number | null;
  skipped: number | null;
  failed: number | null;
};

export type AutonomousTopFindingRow = {
  id?: number;
  rank: number;
  severity: string;
  service: string;
  metric: string;
  behavior: string;
  importance: number;
  firstObserved?: string | null;
  href: string;
  summary?: string;
  observedChange?: string | null;
};

export type AutonomousExecutionRow = {
  id: string;
  scope: string;
  metrics: string;
  status: string;
  completed?: string | null;
  errorSummary?: string | null;
  current?: boolean;
};

export type AutonomousCaseRow = {
  id: number;
  title: string;
  status: string;
  meta: string;
  updatedAt?: string | null;
  href: string;
};

export type AutonomousDashboardCase = {
  id: number;
  case_title: string;
  case_status: string;
  investigation_status: string;
  finding_snapshot?: Record<string, unknown> | null;
  updated_at?: string | null;
};

export type AutonomousDashboardData = {
  summary: AutonomousDashboardSummary;
  selection: AutonomousSelectionSummary;
  topFindings: AutonomousTopFindingRow[];
  behaviorDistribution: Array<{ label: string; count: number }>;
  executionRows: AutonomousExecutionRow[];
  recentCases: AutonomousCaseRow[];
  behaviorFindingCount: number;
  casesScope: 'current_run' | 'history';
};

export type BuildAutonomousDashboardInput = {
  findings: Finding[];
  cases: AutonomousDashboardCase[];
  analysisRuns: AnalysisRun[];
  behaviorFindings?: BehaviorFinding[];
  policyRuns?: AutonomousPolicyRun[];
  previewResult?: AutonomousPreviewResponse | null;
  runResult?: AutonomousRunResponse | null;
  findingHref?: (finding: Finding) => string;
  caseHref?: (caseItem: AutonomousDashboardCase) => string;
};

const CLOSED_CASE_STATUSES = new Set(['resolved', 'closed', 'completed', 'verified']);

function latestPolicyRun(policyRuns: AutonomousPolicyRun[] = []) {
  return [...policyRuns].sort((a, b) => {
    const aTime = new Date(a.completed_at ?? a.started_at ?? a.created_at ?? 0).getTime();
    const bTime = new Date(b.completed_at ?? b.started_at ?? b.created_at ?? 0).getTime();
    return bTime - aTime;
  })[0];
}

function numberOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function openCases(cases: AutonomousDashboardCase[]) {
  return cases.filter((item) => !CLOSED_CASE_STATUSES.has((item.case_status || '').toLowerCase()));
}

function titleCase(value?: string | null) {
  if (!value) return 'Unknown';
  return value
    .replace(/[_-]/g, ' ')
    .split(' ')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function firstObserved(finding: Finding) {
  const comparisonStart = finding.comparison_json?.start_time;
  return typeof comparisonStart === 'string' ? comparisonStart : finding.created_at ?? null;
}

function numericComparisonValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function observedChange(finding: Finding) {
  const comparison = finding.comparison_json ?? {};
  const before = numericComparisonValue(comparison.previous_mean) ?? numericComparisonValue(comparison.first_half_mean);
  const after = numericComparisonValue(comparison.current_mean) ?? numericComparisonValue(comparison.second_half_mean);
  const change = numericComparisonValue(comparison.change_percent) ?? numericComparisonValue(comparison.percent_change);
  if (before === null || after === null) return null;
  const direction = after >= before ? 'increased' : 'decreased';
  const changeText = change === null ? '' : ` (${change >= 0 ? '+' : ''}${change.toFixed(1)}%)`;
  return `${direction} from ${before.toFixed(2)} to ${after.toFixed(2)}${changeText}`;
}

function executionRowsFromPolicyRuns(policyRuns: AutonomousPolicyRun[]) {
  return policyRuns.slice(0, 7).map((run) => {
    const snapshot = run.policy_snapshot ?? {};
    const scope = snapshot.scope_summary as Record<string, unknown> | undefined;
    const services = Array.isArray(scope?.services_resolved) ? scope?.services_resolved : [];
    const namespaces = Array.isArray(scope?.namespaces_resolved) ? scope?.namespaces_resolved : [];
    const scopeLabel = services.length
      ? String(services.slice(0, 2).join(', '))
      : namespaces.length
        ? String(namespaces.slice(0, 2).join(', '))
        : run.policy_id || run.trigger || 'autonomous scope';
    return {
      id: run.id,
      scope: scopeLabel,
      metrics: `${run.jobs_completed ?? run.jobs_planned ?? run.metrics_selected ?? 0} metrics`,
      status: run.status,
      completed: run.completed_at ?? run.updated_at ?? null,
      errorSummary: run.error_summary ?? null,
      current: false,
    };
  });
}

function executionRowsFromAnalysisRuns(analysisRuns: AnalysisRun[]) {
  return analysisRuns.slice(0, 7).map((run) => ({
    id: run.id,
    scope: `${run.service || 'unknown'} / ${run.metric_name || 'unknown'}`,
    metrics: `${run.sample_count ?? 0} samples`,
    status: run.status,
    completed: run.end_time ?? run.created_at ?? null,
    current: false,
  }));
}

function executionRowsFromCurrentRun(run: AutonomousRunResponse | null): AutonomousExecutionRow[] {
  if (!run) return [];
  const scopes = Array.from(new Set(run.results.map((result) => result.service).filter(Boolean))).slice(0, 2);
  const failedErrors = run.results.map((result) => result.error).filter(Boolean);
  return [{
    id: `current:${run.requested_end}`,
    scope: scopes.length ? scopes.join(', ') : 'current run',
    metrics: `${run.executed_jobs} executed / ${run.planned_jobs} planned`,
    status: run.status,
    completed: run.requested_end,
    errorSummary: failedErrors.length ? failedErrors.slice(0, 2).join('; ') : null,
    current: true,
  }];
}

export function buildAutonomousDashboardData(input: BuildAutonomousDashboardInput): AutonomousDashboardData {
  const policyRun = latestPolicyRun(input.policyRuns);
  const preview = input.previewResult ?? null;
  const run = input.runResult ?? null;
  const currentAnalysisRunIds = new Set((run?.results ?? []).map((result) => result.analysis_run_id).filter(Boolean) as string[]);
  const hasCurrentRunScope = currentAnalysisRunIds.size > 0;

  const discovered = numberOrNull(policyRun?.metrics_discovered) ?? numberOrNull(preview?.metrics_discovered);
  const selected = numberOrNull(policyRun?.metrics_selected) ?? numberOrNull(preview?.metrics_selected) ?? numberOrNull(preview?.metrics_matched);
  const excluded = discovered !== null && selected !== null ? Math.max(discovered - selected, 0) : numberOrNull(preview?.metrics_excluded);
  const reductionPercent = discovered && selected !== null ? ((discovered - selected) / discovered) * 100 : null;

  const executed = numberOrNull(policyRun?.jobs_completed) ?? numberOrNull(run?.executed_jobs);
  const skipped = numberOrNull(policyRun?.jobs_skipped) ?? numberOrNull(run?.skipped_jobs);
  const failed = numberOrNull(policyRun?.jobs_failed) ?? numberOrNull(run?.failed_jobs);

  const findingHref = input.findingHref ?? (() => '/findings?window=24h');
  const caseHref = input.caseHref ?? ((caseItem) => `/cases/${caseItem.id}`);
  const scopedFindings = hasCurrentRunScope ? input.findings.filter((finding) => finding.analysis_run_id && currentAnalysisRunIds.has(finding.analysis_run_id)) : input.findings;
  const scopedCases = hasCurrentRunScope ? input.cases.filter((caseItem) => caseItem.analysis_run_id && currentAnalysisRunIds.has(caseItem.analysis_run_id)) : input.cases;
  const sortedFindings = [...scopedFindings].sort((a, b) => (b.importance_score ?? 0) - (a.importance_score ?? 0));

  const distribution = sortedFindings.reduce<Record<string, number>>((acc, finding) => {
    const label = titleCase(finding.category || finding.health_status || 'other');
    acc[label] = (acc[label] ?? 0) + 1;
    return acc;
  }, {});

  const recentCases = [...scopedCases]
    .sort((a, b) => new Date(b.updated_at ?? 0).getTime() - new Date(a.updated_at ?? 0).getTime())
    .slice(0, 5)
    .map((caseItem) => {
      const snapshot = caseItem.finding_snapshot ?? {};
      const serviceMetric = [snapshot.service, snapshot.metric_name].filter(Boolean).join(' / ');
      return {
        id: caseItem.id,
        title: `Case #${caseItem.id} - ${caseItem.case_title}`,
        status: `${caseItem.case_status} · ${caseItem.investigation_status}`,
        meta: serviceMetric || 'No linked metric',
        updatedAt: caseItem.updated_at,
        href: caseHref(caseItem),
      };
    });

  return {
    summary: {
      metricsDiscovered: discovered,
      candidatesSelected: selected,
      findingsGenerated: scopedFindings.length,
      casesOpen: openCases(scopedCases).length,
      executed,
      skipped,
      failed,
    },
    selection: {
      title: 'Metric Selection',
      discovered,
      selected,
      excluded,
      reductionPercent,
      selectedLabel: 'Selected by monitoring policy',
      screeningEnabled: false,
      reasons: [],
    },
    topFindings: sortedFindings.slice(0, 8).map((finding, index) => ({
      id: finding.id,
      rank: index + 1,
      severity: finding.health_status,
      service: finding.service || 'unknown',
      metric: finding.metric_name,
      behavior: titleCase(finding.category),
      importance: finding.importance_score,
      firstObserved: firstObserved(finding),
      href: findingHref(finding),
      summary: finding.summary,
      observedChange: observedChange(finding),
    })),
    behaviorDistribution: Object.entries(distribution)
      .map(([label, count]) => ({ label, count }))
      .sort((a, b) => b.count - a.count),
    executionRows: [
      ...executionRowsFromCurrentRun(run),
      ...(input.policyRuns?.length ? executionRowsFromPolicyRuns(input.policyRuns) : executionRowsFromAnalysisRuns(input.analysisRuns)),
    ].slice(0, 7),
    recentCases,
    behaviorFindingCount: input.behaviorFindings?.length ?? 0,
    casesScope: hasCurrentRunScope ? 'current_run' : 'history',
  };
}
