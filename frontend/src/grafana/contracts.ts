import type { AnalysisRun, TimeseriesPoint } from '../types';

export type GrafanaQueryTarget = {
  datasource: string;
  service: string;
  metric: string;
  timeRange: {
    from: string;
    to: string;
  };
};

export type GrafanaAnalysisStatus = 'idle' | 'running' | 'complete' | 'error';

export type GrafanaAnalysisSignal = {
  id: string;
  analyzer_id: string;
  signal_type: string;
  summary: string;
  severity?: string;
  confidence?: number;
  importance_score: number;
  start_time?: string;
  end_time?: string;
  evidence?: Record<string, unknown>;
};

export type GrafanaAnalyzerRoutingDecision = {
  analyzer_id: string;
  display_name: string;
  eligible: boolean;
  recommendation: string;
  final_score: number;
  reasons: string[];
  warnings: string[];
};

export type GrafanaAnalysisFinding = {
  id: number;
  title: string;
  summary: string;
  category: string;
  health_status: string;
  importance_score: number;
  investigation_priority: number;
  signal_ids: string[];
  comparison_json?: Record<string, unknown>;
};

export type GrafanaAnalyzerExecution = {
  router_analyzer_id: string;
  display_name?: string;
  recommendation?: string;
  selected?: boolean;
  pipeline_analyzer_ids?: string[];
  executed_pipeline_analyzer_ids?: string[];
  execution_status: string;
  execution_reason?: string | null;
};

export type GrafanaBehaviorFinding = {
  id: number;
  title: string;
  summary: string;
  severity: string;
  confidence: number;
  correlation: Record<string, unknown>;
};

export type GrafanaAnalysisResult = {
  runId: string;
  status: GrafanaAnalysisStatus;
  datasource: string;
  datasourceUid?: string;
  service: string;
  metric: string;
  promql?: string;
  from: string;
  to: string;
  summary: string;
  signals: GrafanaAnalysisSignal[];
  findings: GrafanaAnalysisFinding[];
  behaviorFindings: GrafanaBehaviorFinding[];
  timeseries: TimeseriesPoint[];
  analysisRuns: AnalysisRun[];
  seriesCount?: number;
  sampleCount?: number;
  warnings?: string[];
  durationMs?: number;
  analyzerSelectionMode?: string;
  analyzerRouting?: GrafanaAnalyzerRoutingDecision[];
  executedAnalyzers?: string[];
  analyzerExecutions?: GrafanaAnalyzerExecution[];
};

export type GrafanaQuestion = {
  id: string;
  label: string;
  description: string;
  contributors: string[];
  available: boolean;
};

export type GrafanaQuestionAnswer = {
  question_id: string;
  headline: string;
  answer: string;
  status: string;
  priority: string;
  confidence: number;
  key_points: string[];
  evidence_signal_ids: string[];
};

export type GrafanaCaseCreateResponse = {
  case_id: number;
  finding_id: number;
  case_status: string;
  memory_status: string;
};

export type GrafanaCaseNote = {
  timestamp?: string;
  note?: string;
};

export type GrafanaCase = {
  id: number;
  finding_id: number;
  analysis_run_id: string;
  case_title: string;
  case_status: string;
  finding_snapshot: Record<string, unknown>;
  investigation_status: string;
  investigation_notes: GrafanaCaseNote[];
  root_cause_status: string;
  root_cause_summary: string | null;
  root_cause_confidence: number | null;
  root_cause_verified: boolean;
  corrective_action: string | null;
  outcome_status: string;
  outcome_summary: string | null;
  memory_status: string;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
};

export type MonitoringCategory =
  | 'performance'
  | 'capacity'
  | 'availability'
  | 'reliability'
  | 'infrastructure'
  | 'messaging'
  | 'kubernetes'
  | 'custom';

export type AutonomousPreviewRequest = {
  datasource: 'prometheus';
  backend: string;
  scope: {
    environment?: string | null;
    services: string[];
    namespaces: string[];
    all_services: boolean;
    all_namespaces: boolean;
    service_label: string;
    namespace_label: string;
    environment_label: string;
  };
  monitoring_selection?: {
    categories: MonitoringCategory[];
    custom_constraints?: {
      include_patterns: string[];
      exclude_patterns: string[];
      required_labels: Record<string, string>;
      explicit_metrics: string[];
      aggregation?: string | null;
      group_by: string[];
    } | null;
  };
  monitoring_categories: MonitoringCategory[];
  execution: {
    interval: string;
    analysis_window: string;
    max_metrics_per_run: number;
    max_parallel_jobs: number;
  };
  custom_constraints: {
    include_patterns: string[];
    exclude_patterns: string[];
    required_labels: Record<string, string>;
    explicit_metrics: string[];
  };
};

export type AutonomousPolicy = {
  id: string;
  name: string;
  datasource: string;
  backend: string;
  scope: AutonomousPreviewRequest['scope'];
  monitoring_selection: NonNullable<AutonomousPreviewRequest['monitoring_selection']>;
  execution: AutonomousPreviewRequest['execution'];
  enabled: boolean;
  schedule_minutes: number | null;
  next_run_at: string | null;
  last_run_status: string | null;
  consecutive_failures: number;
  created_at: string | null;
  updated_at: string | null;
};

export type AutonomousPolicySaveRequest = {
  name: string;
  datasource: string;
  backend: string;
  scope: AutonomousPreviewRequest['scope'];
  monitoring_selection: NonNullable<AutonomousPreviewRequest['monitoring_selection']>;
  execution: AutonomousPreviewRequest['execution'];
  schedule_minutes: number | null;
};

export type AutonomousPlanItem = {
  service?: string | null;
  namespace?: string | null;
  environment?: string | null;
  metric_name: string;
  category?: MonitoringCategory | null;
  concept?: string | null;
  concepts?: string[];
  metric_type?: string | null;
  selector?: string;
  transformation: string;
  aggregation: string;
  group_by: string[];
  promql: string;
  confidence: number;
  selection_reason?: string | null;
  matched_rule?: string | null;
  aggregation_strategy: string;
  estimated_series_count: number;
  planned: boolean;
  exclusion_reason?: string | null;
  analysis_window: string;
  explanation?: string | null;
  planned_request?: Record<string, unknown> | null;
};

export type AutonomousPreviewResponse = {
  scope_summary: {
    services?: number;
    namespaces?: number;
    services_resolved?: string[];
    namespaces_resolved?: string[];
    environment?: string | null;
    label_mapping?: Record<string, string | null>;
    selector?: string;
    series_discovered?: number;
    series_available?: number | null;
    truncated?: boolean;
    starved_metrics_count?: number;
    starved_metrics?: string[];
  };
  monitoring_summary?: {
    categories?: MonitoringCategory[];
    concepts?: string[];
  };
  metrics_discovered: number;
  metrics_classified?: number;
  metrics_selected?: number;
  metrics_matched: number;
  metrics_excluded: number;
  planned_jobs: number;
  budget_limited_jobs?: number;
  budget_limited: number;
  series_discovered?: number;
  series_available?: number | null;
  truncated?: boolean;
  starved_metrics_count?: number;
  starved_metrics?: string[];
  warnings: string[];
  items: AutonomousPlanItem[];
};

export type AutonomousRunJobResult = {
  metric_name: string;
  service?: string | null;
  category?: MonitoringCategory | null;
  concept?: string | null;
  promql: string;
  status: 'completed' | 'skipped' | 'failed';
  analysis_run_id?: string | null;
  sample_count: number;
  series_count: number;
  signal_count: number;
  findings_count: number;
  behavior_findings_count: number;
  error?: string | null;
  warnings: string[];
};

export type AutonomousRunResponse = {
  status: 'completed' | 'partial' | 'failed' | 'dry_run';
  policy_run_id?: string | null;
  planned_jobs: number;
  executed_jobs: number;
  skipped_jobs: number;
  failed_jobs: number;
  analysis_window: string;
  requested_start: string;
  requested_end: string;
  step: string;
  preview: AutonomousPreviewResponse;
  results: AutonomousRunJobResult[];
  warnings: string[];
};
