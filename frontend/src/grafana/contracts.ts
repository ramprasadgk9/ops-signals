import type { AnalysisRun, BehaviorFinding, FindingPlain, FindingTrust, TimeseriesPoint } from '../types';

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
  routing_reason?: string;
  parameters_tested?: { detected_profiles?: string[] } | null;
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
  trust?: FindingTrust | null;
  plain?: FindingPlain | null;
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
  failed_pipeline_analyzer_ids?: string[];
  /** Why it ran or didn't; see intelligence/analyzer_selection.py RUN_REASON_TEXT. Absent on older runs. */
  run_reason?: string | null;
  shapes?: string[];
  missing_library?: string | null;
  /** Whether its signals are part of a finding; null when it didn't run or the run predates this. */
  in_finding?: boolean | null;
  /** What the analyzer looks for, in plain words, from its registration. */
  description?: string | null;
};

export type GrafanaBehaviorFinding = {
  id: number;
  title: string;
  summary: string;
  severity: string;
  confidence: number;
  correlation: Record<string, unknown>;
  service?: string | null;
  /** The case already opened from this behavior, if any. */
  case_id?: number | null;
} & Partial<Pick<BehaviorFinding,
  'definition_id' | 'definition_version' | 'analysis_run_id' | 'input_metrics_json' | 'facts_json' | 'matched_conditions_json'
  | 'correlation_json' | 'occurrence_count' | 'last_seen_at'>>;

export type GrafanaAnalysisResult = {
  runId: string;
  status: GrafanaAnalysisStatus;
  datasource: string;
  datasourceUid?: string;
  service: string;
  metric: string;
  promql?: string;
  /** Set when per-pod series were combined into the one analyzed line, in plain words. */
  analyzedAs?: string | null;
  from: string;
  to: string;
  summary: string;
  signals: GrafanaAnalysisSignal[];
  findings: GrafanaAnalysisFinding[];
  behaviorFindings: GrafanaBehaviorFinding[];
  timeseries: TimeseriesPoint[];
  /** Set for runs through a backend connection: the cluster analysed and the connection's name. */
  cluster?: string | null;
  connection?: string | null;
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

export type GrafanaBehaviorCaseCreateResponse = {
  case_id: number;
  behavior_finding_id: number;
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
  /** The Grafana user who opened it, and who closed it; absent when not done through Grafana. */
  created_by?: string | null;
  resolved_by?: string | null;
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
  /** Named Prometheus connection (e.g. one Mimir tenant); omitted = the default connection. */
  connection_id?: string;
  scope: {
    environment?: string | null;
    services: string[];
    namespaces: string[];
    all_services: boolean;
    all_namespaces: boolean;
    service_label: string;
    namespace_label: string;
    environment_label: string;
    /** Clusters behind one Mimir/Thanos endpoint; omitted = all clusters. */
    clusters?: string[];
    all_clusters?: boolean;
    cluster_label?: string | null;
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
  connection_id?: string;
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
  /** Who made it and who last changed it, when that came through Grafana. */
  created_by?: string | null;
  edited_by?: string | null;
  edited_at?: string | null;
};

export type AutonomousPolicySaveRequest = {
  name: string;
  datasource: string;
  backend: string;
  connection_id?: string;
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
  would_be_category?: MonitoringCategory[];
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
  budget_excluded_metrics_count?: number;
  budget_excluded_metrics?: string[];
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
  excluded_jobs?: number;
  failed_jobs: number;
  budget_limited_jobs?: number;
  budget_excluded_metrics_count?: number;
  budget_excluded_metrics?: string[];
  summary?: Record<string, any>;
  analysis_window: string;
  requested_start: string;
  requested_end: string;
  step: string;
  preview: AutonomousPreviewResponse;
  results: AutonomousRunJobResult[];
  warnings: string[];
};

export type TicketingStatus = {
  enabled: boolean;
  provider: string;
  provider_configured: boolean;
  webhook_secret_configured: boolean;
};

export type CaseTicketLink = {
  case_id: number;
  provider: string;
  remote_id: string;
  display_key: string;
  ticket_url: string;
  observed_remote_status?: string | null;
  last_synced_at?: string | null;
  sync_status: string;
};

export type CaseTicketOperation = {
  operation_id: string;
  case_id: number;
  provider: string;
  operation_type: string;
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'ambiguous_outcome' | 'superseded';
  attempts: number;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
};

export type CaseTicketEvent = {
  id: number;
  case_id: number;
  provider: string;
  remote_event_id: string;
  event_type: string;
  author?: string | null;
  summary: string;
  occurred_at: string;
  created_at: string;
};

export type AmbiguousResolutionPayload = {
  action: 'check_again' | 'link_existing' | 'force_create_new';
  remote_key?: string;
};

