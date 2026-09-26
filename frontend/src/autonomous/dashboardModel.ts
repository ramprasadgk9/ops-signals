import type { AnalysisRun, BehaviorFinding, Finding } from '../types';
import type { AutonomousPreviewResponse, AutonomousRunResponse, MonitoringCategory } from '../grafana/contracts';

export type { AutonomousPreviewResponse, AutonomousRunResponse, MonitoringCategory };

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
  budget_limited_jobs?: number | null;
  budget_excluded_metrics_count?: number | null;
  budget_excluded_metrics?: string[] | null;
  findings_created?: number | null;
  error_summary?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type AutonomousExclusionMetric = {
  metricName: string;
  service: string | null;
  namespace: string | null;
  matchedRule?: string | null;
  supersededByMetric?: string | null;
};

export type AutonomousExclusionReason = {
  reason: string;
  label: string;
  description: string;
  actionable: boolean;
  count: number;
  wouldEnableCategories?: Array<{ category: string; count: number }>;
  metrics: AutonomousExclusionMetric[];
};

export type AutonomousSelectionSummary = {
  title: string;
  discovered: number | null;
  selected: number | null;
  excluded: number | null;
  reductionPercent: number | null;
  selectedLabel: string;
  screeningEnabled: boolean;
  reasons: AutonomousExclusionReason[];
  reasonsAvailable: boolean;
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
  analysis_run_id?: string | null;
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
  // Analysis run ids of the latest finished scheduled run. Used to scope findings and cases when
  // there is no manual run in this page (which always takes priority).
  scheduledRunAnalysisRunIds?: string[];
  findingHref?: (finding: Finding) => string;
  caseHref?: (caseItem: AutonomousDashboardCase) => string;
};

const CLOSED_CASE_STATUSES = new Set(['resolved', 'closed', 'completed', 'verified']);

const EXCLUSION_REASON_LABELS: Record<string, string> = {
  category_disabled: 'Category not enabled',
  no_matching_rule: 'No rule recognizes this metric',
  static_metadata_metric: 'System/internal metric',
  created_timestamp: 'System/internal metric',
  custom_exclude_pattern: 'Excluded by your custom pattern',
  missing_required_label: 'Missing required labels',
  budget_limit: "Cut by this run's metric budget",
  duplicate_lower_rank: 'Duplicate of a higher-confidence metric',
};

// Plain-language explanation shown under each bucket, keyed by the bucket's label
// (not the raw reason code) since several reason codes can share one label/bucket.
const EXCLUSION_REASON_DESCRIPTIONS: Record<string, string> = {
  'Category not enabled': 'These metrics match a known pattern, but the monitoring category they belong to is switched off in your policy.',
  'No rule recognizes this metric': "\"Rule\" means the system's built-in library of exact metric names and name patterns (e.g. anything matching *_latency_seconds is known to be a latency metric) - it's not something you configure. None of those rules recognize this metric's name, so the system can't tell what it measures.",
  'System/internal metric': 'These are metadata or bookkeeping metrics (like names ending in _info or _created), not real operational signals - excluded on purpose.',
  'Excluded by your custom pattern': 'These matched an "Exclude pattern" you set yourself, in Configure -> Monitoring Categories -> Custom -> Exclude patterns. Expand the list below to see exactly which pattern matched each metric.',
  'Missing required labels': 'These metrics are missing a label your policy requires (like service or namespace), so they can\'t be attributed to anything.',
  "Cut by this run's metric budget": "These metrics qualified for analysis, but this run's metric limit was reached before they could be included.",
  'Duplicate of a higher-confidence metric': 'These metrics would have been selected, but another metric already covers the same service, category, and concept with a more reliable classification (an exact known metric beats a fuzzy name-pattern match) - the system kept that one instead of analyzing both. Expand the list to see which metric won each match.',
};

// Reasons a policy change can actually fix - the rest are either intentional
// (system metrics) or need something other than an enable/disable toggle.
const ACTIONABLE_EXCLUSION_REASONS = new Set(['category_disabled']);

function exclusionReasonLabel(reason: string): string {
  return EXCLUSION_REASON_LABELS[reason] ?? 'Excluded from this preview';
}

function exclusionReasonDescription(label: string): string {
  return EXCLUSION_REASON_DESCRIPTIONS[label] ?? 'These metrics were not selected in this preview.';
}

// Turns an internal matched_rule id (e.g. "custom.exclude.foo_.*", "static.suffix._info")
// into the plain-language detail shown next to a metric in an exclusion bucket's list.
// Only the first two dots are structural (scope.kind.value) - regex patterns in the
// value itself routinely contain dots (e.g. ".*build.*info.*"), so a plain split('.')
// would mangle them. Slice on explicit indices instead of splitting the whole string.
export function formatMatchedRule(rule: string | null | undefined): string | null {
  if (!rule) return null;
  const firstDot = rule.indexOf('.');
  const secondDot = firstDot === -1 ? -1 : rule.indexOf('.', firstDot + 1);
  if (firstDot === -1 || secondDot === -1) return rule;
  const scope = rule.slice(0, firstDot);
  const kind = rule.slice(firstDot + 1, secondDot);
  const value = rule.slice(secondDot + 1);
  if (scope === 'custom' && kind === 'exclude') return `matched your exclude pattern "${value}"`;
  if (scope === 'static' && kind === 'exact') return `blocklisted metric name`;
  if (scope === 'static' && kind === 'suffix') return `name ends with "${value}"`;
  if (scope === 'static' && kind === 'pattern') return `matched system pattern "${value}"`;
  return rule;
}

// Same grouping the backend uses to dedupe (environment, namespace, service, category,
// concept) - lets the frontend name which planned metric "won" a duplicate-rank exclusion
// without needing the backend to carry that link explicitly.
function logicalKey(item: { environment?: string | null; namespace?: string | null; service?: string | null; category?: string | null; concept?: string | null }): string {
  return [item.environment ?? '', item.namespace ?? '', item.service ?? '', item.category ?? '', item.concept ?? ''].join('|');
}

function buildExclusionReasons(preview: AutonomousPreviewResponse | null): AutonomousExclusionReason[] {
  if (!preview) return [];
  const winnerByKey = new Map<string, string>();
  for (const item of preview.items) {
    if (item.planned) winnerByKey.set(logicalKey(item), item.metric_name);
  }
  const buckets = new Map<string, AutonomousExclusionReason>();
  for (const item of preview.items) {
    if (item.planned) continue;
    const reason = item.exclusion_reason ?? 'unknown';
    const label = exclusionReasonLabel(reason);
    // Group by label so e.g. the two "system metric" backend reasons present as one bucket.
    const key = label;
    let bucket = buckets.get(key);
    if (!bucket) {
      bucket = { reason, label, description: exclusionReasonDescription(label), actionable: ACTIONABLE_EXCLUSION_REASONS.has(reason), count: 0, metrics: [] };
      buckets.set(key, bucket);
    }
    bucket.count += 1;
    if (bucket.metrics.length < 200) {
      bucket.metrics.push({
        metricName: item.metric_name,
        service: item.service ?? null,
        namespace: item.namespace ?? null,
        matchedRule: item.matched_rule ?? null,
        supersededByMetric: reason === 'duplicate_lower_rank' ? winnerByKey.get(logicalKey(item)) ?? null : null,
      });
    }
    // Only the "category disabled" bucket is fixable by enabling a category - other
    // reasons (duplicate rank, budget cap, blocklist) can carry a would_be_category
    // too, but the category is often already enabled there, so an "Enable" action
    // would be a no-op or actively misleading.
    if (reason === 'category_disabled' && item.would_be_category?.length) {
      bucket.wouldEnableCategories = bucket.wouldEnableCategories ?? [];
      for (const category of item.would_be_category) {
        const existing = bucket.wouldEnableCategories.find((entry) => entry.category === category);
        if (existing) existing.count += 1;
        else bucket.wouldEnableCategories.push({ category, count: 1 });
      }
    }
  }
  return [...buckets.values()].sort((a, b) => b.count - a.count);
}

// A run that has finished (successfully or not) - one still in progress has no complete set of
// jobs to show yet.
export function latestFinishedPolicyRun(policyRuns: AutonomousPolicyRun[] = []) {
  return latestPolicyRun(policyRuns.filter((run) => Boolean(run.completed_at)));
}

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
    const budgetLimited = run.budget_limited_jobs ?? (snapshot.budget_limited_jobs as number | undefined);
    const budgetNotice = budgetLimited && budgetLimited > 0 ? ` (${budgetLimited} budget-excluded)` : '';
    return {
      id: run.id,
      scope: scopeLabel,
      metrics: `${run.jobs_completed ?? run.jobs_planned ?? run.metrics_selected ?? 0} metrics${budgetNotice}`,
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
  const budgetNotice = run.budget_limited_jobs && run.budget_limited_jobs > 0
    ? ` (${run.budget_limited_jobs} budget-excluded)`
    : '';
  return [{
    id: `current:${run.requested_end}`,
    scope: scopes.length ? scopes.join(', ') : 'current run',
    metrics: `${run.executed_jobs} executed / ${run.planned_jobs} planned${budgetNotice}`,
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
  const currentAnalysisRunIds = new Set(
    (run ? run.results.map((result) => result.analysis_run_id) : input.scheduledRunAnalysisRunIds ?? []).filter(Boolean) as string[],
  );
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
      reasons: buildExclusionReasons(preview),
      reasonsAvailable: preview !== null,
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
