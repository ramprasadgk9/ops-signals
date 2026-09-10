export type Question = {
  id: string;
  label: string;
  description: string;
  contributors: string[];
  available: boolean;
  confidence?: number;
};

export type QuestionAnswer = {
  question_id: string;
  headline: string;
  answer: string;
  status: string;
  priority: string;
  confidence: number;
  key_points: string[];
  evidence_signal_ids: string[];
};

export type Capability = {
  id: string;
  analyzer_id: string;
  title: string;
  description: string;
  enabled: boolean;
  metadata_json: {
    status?: string;
    supported_question_ids?: string[];
  };
};

export type BehaviorDefinition = {
  id: string;
  enabled: boolean;
  version: number;
  title: string;
  description: string;
  scope: Record<string, unknown>;
  inputs: Array<Record<string, unknown>>;
  conditions: Record<string, Array<Record<string, unknown>>>;
  correlation: Record<string, unknown>;
  output: Record<string, unknown>;
};

export type BehaviorFinding = {
  id: number;
  behavior_id: string;
  definition_id: string;
  definition_version: number;
  title: string;
  summary: string;
  category: string;
  severity: string;
  service?: string;
  analysis_run_id?: string;
  input_metrics_json: Record<string, unknown>;
  facts_json: Record<string, unknown>;
  evidence_json: string[];
  matched_conditions_json: Array<Record<string, unknown>>;
  confidence: number;
  correlation_json: Record<string, unknown>;
  case_id?: number | null;
  created_at: string;
};

export type BehaviorEvaluation = {
  definition_id: string;
  definition_version: number;
  title: string;
  description: string;
  matched: boolean;
  confidence: number;
  service?: string | null;
  analysis_run_id?: string | null;
  facts: Record<string, unknown>;
  matched_conditions: Array<Record<string, unknown>>;
  evidence: string[];
  correlation: Record<string, unknown>;
};

export type Signal = {
  id: string;
  signal_type: string;
  analyzer_id?: string;
  metric_name: string;
  service?: string;
  severity?: string;
  confidence?: number;
  importance_score: number;
  start_time?: string;
  end_time?: string;
  summary?: string;
  evidence: Record<string, unknown>;
  analysis_run_id?: string;
};

export type Finding = {
  id?: number;
  service?: string;
  metric_name: string;
  title: string;
  summary: string;
  category: string;
  health_status: string;
  importance_score: number;
  investigation_priority: number;
  signal_ids: string[];
  comparison_json: Record<string, unknown>;
  analysis_run_id?: string;
  created_at?: string;
};

export type OperationalCase = {
  id: number;
  finding_id: number;
  analysis_run_id: string;
  case_title: string;
  case_status: string;
  finding_snapshot: Finding;
  investigation_status: string;
  investigation_notes: Array<{ timestamp?: string; note: string }>;
  root_cause_status: string;
  root_cause_summary?: string;
  root_cause_confidence?: number;
  root_cause_verified: boolean;
  corrective_action?: string;
  outcome_status: string;
  outcome_summary?: string;
  memory_status: string;
  created_at: string;
  updated_at: string;
  resolved_at?: string;
};

export type SeverityTrendPoint = {
  timestamp: string;
  critical: number;
  high: number;
  medium: number;
  low: number;
};

export type CategoryBreakdown = {
  category: string;
  count: number;
};

export type OverviewSummaryResponse = {
  generated_at: string;
  window: '24h' | '7d';
  active_findings: number;
  open_cases: number;
  behavior_changes: number;
  impacted_services: number;
  memory_items: number;
  severity_trend: SeverityTrendPoint[];
  category_breakdown: CategoryBreakdown[];
};

export type MemoryStatsResponse = {
  generated_at: string;
  enabled: boolean;
  status: string;
  indexed_cases: number;
  not_indexed_cases: number;
  stale_cases: number;
  error_cases: number;
  total_cases: number;
  source: string;
};

export type PrometheusConnection = {
  id: string;
  name: string;
  base_url?: string | null;
  configured: boolean;
};

export type PrometheusConnectionsResponse = {
  connections: PrometheusConnection[];
};

export type PrometheusLabelValuesResponse = {
  connection_id: string;
  label: string;
  values: string[];
};

export type PrometheusConnectionTestResponse = {
  available: boolean;
  version?: string | null;
  latency_ms?: number | null;
  message: string;
};

export type AnalyzerConfigSuggestion = {
  id: number;
  analyzer_id: string;
  lab_name: string;
  suggestion_name: string;
  yaml_text: string;
  implementation_json: Record<string, unknown>;
  finding_rules_json: Record<string, unknown>;
  benchmark_summary_json: Record<string, unknown>;
  pass_fail_status: 'pass' | 'fail' | 'unknown';
  created_by: string;
  created_at: string;
};

export type AnalyzerConfigSuggestionInput = Omit<AnalyzerConfigSuggestion, 'id' | 'created_at'>;

export type PrometheusPreviewSeries = {
  labels: Record<string, string>;
  samples: Array<{ timestamp: string; value: number | null }>;
};

export type PrometheusPreviewResponse = {
  query: string;
  start: string;
  end: string;
  step: string;
  step_seconds: number;
  series_count: number;
  sample_count: number;
  series: PrometheusPreviewSeries[];
  warnings: string[];
};

export type DirectPrometheusAnalysisRequest = {
  connection_id: string;
  query: string;
  service: string;
  metric: string;
  start: string;
  end: string;
  step: string;
  analyzer?: string | null;
  execution_mode: 'persist';
};

export type DirectPrometheusAnalysisResponse = {
  analysis_run_id: string;
  provider: string;
  source_type: string;
  connection_id: string;
  connection_name: string;
  service: string;
  metric_name: string;
  query: string;
  requested_start: string;
  requested_end: string;
  actual_start?: string | null;
  actual_end?: string | null;
  step: string;
  step_seconds: number;
  sample_count: number;
  series_count: number;
  findings_count: number;
  signal_count: number;
  behavior_findings_count: number;
  warnings: string[];
  analyzer_selection_mode: string;
  analyzer_routing: Array<Record<string, unknown>>;
  executed_analyzers: string[];
  analyzer_executions?: AnalyzerExecution[];
  series: PrometheusPreviewSeries[];
  signals: Signal[];
  findings: Finding[];
};

export type AnalyzerExecution = {
  router_analyzer_id?: string;
  display_name?: string;
  recommendation?: string;
  selected?: boolean;
  pipeline_analyzer_ids?: string[];
  executed_pipeline_analyzer_ids?: string[];
  failed_pipeline_analyzer_ids?: string[];
  execution_status?: 'completed' | 'skipped' | 'failed' | string;
  execution_reason?: string | null;
};

export type AnalysisRun = {
  id: string;
  source_type: string;
  file_name?: string | null;
  provider: string;
  service: string;
  metric_name: string;
  start_time: string;
  end_time: string;
  sample_count: number;
  status: string;
  router_version?: string | null;
  feature_extractor_version?: string | null;
  analyzer_registry_version?: string | null;
  series_profile_json?: Record<string, unknown> | null;
  router_decisions_json?: Array<{
    analyzer_id?: string;
    analyzer?: string;
    display_name?: string;
    eligible?: boolean;
    eligibility_score?: number;
    suitability_score?: number;
    final_score?: number;
    recommendation?: 'RECOMMENDED' | 'OPTIONAL' | 'NOT_RECOMMENDED' | 'REJECTED' | 'OVERRIDDEN' | string;
    reasons?: string[];
    warnings?: string[];
    explanation?: string;
    parameters_tested?: Record<string, unknown>;
  }> | null;
  executed_analyzers_json?: Array<{
    router_analyzer_id?: string;
    pipeline_analyzer_id?: string;
  }> | null;
  generated_findings_json?: Array<Record<string, unknown>> | null;
  created_at: string;
};

export type ExperimentEvent = {
  event_id: string;
  event_type: string;
  index?: number | null;
  timestamp?: string | null;
  value?: number | null;
  severity?: string | null;
  score?: number | null;
  window_start?: string | null;
  window_end?: string | null;
  details: Record<string, unknown>;
  interpretation?: string | null;
  technical_summary?: string | null;
};

export type ExperimentResult = {
  experiment_id: string;
  dataset: {
    name: string;
    file_path: string;
    rows: number;
    columns: number;
    timestamp_column: string;
    value_column: string;
    sampling_interval_seconds?: number | null;
    start_time?: string | null;
    end_time?: string | null;
    min_value?: number | null;
    max_value?: number | null;
    missing_values: number;
    duplicate_timestamps: number;
    timestamps_sorted: boolean;
  };
  analyzer: {
    name: string;
    algorithm?: string | null;
    model?: string | null;
    parameters: Record<string, unknown>;
  };
  preprocessing: { normalization: string };
  execution: {
    status: string;
    started_at?: string | null;
    completed_at?: string | null;
    execution_time_seconds?: number | null;
  };
  results: {
    event_type: string;
    event_count: number;
    events: ExperimentEvent[];
  };
  metrics: {
    precision?: number | null;
    recall?: number | null;
    f1_score?: number | null;
  };
  artifacts: {
    raw_plot?: string | null;
    result_plot?: string | null;
    comparison_plot?: string | null;
  };
  observations: string[];
  recommendation: {
    title?: string | null;
    summary?: string | null;
    recommended_configuration?: string | null;
    suitable_for: string[];
    not_suitable_for: string[];
    limitations: string[];
  };
  created_at: string;
  plain_language_summary?: string | null;
  event_summaries: string[];
};

export type ExperimentComparison = {
  analyzer: string;
  comparison_summary: string;
  shared_event_count: number;
  unique_event_count: number;
  experiment_ids: string[];
  items: Array<{ experiment_id: string; penalty?: number | null; event_count: number; summary?: string | null }>;
};

export type RouterDecision = {
  analyzer: string;
  display_name: string;
  eligible: boolean;
  eligibility_score: number;
  suitability_score: number;
  final_score: number;
  recommendation: 'RECOMMENDED' | 'OPTIONAL' | 'NOT_RECOMMENDED' | 'REJECTED' | 'OVERRIDDEN' | string;
  reasons: string[];
  warnings: string[];
  explanation: string;
  parameters_tested: Record<string, unknown>;
};

export type RouterResponse = {
  summary: string;
  validation: { valid: boolean; status: string; reasons: string[]; warnings: string[] };
  profile: Record<string, unknown>;
  analyzers: RouterDecision[];
  export_path?: string | null;
};

export type TimeseriesPoint = {
  timestamp: string;
  value: number;
  service: string;
  metric_name: string;
  analysis_run_id: string;
};

export type CsvRunResult = {
  analysis_run_id: string;
  file_name?: string | null;
  provider: string;
  source_type: string;
  service: string;
  metric_name: string;
  sample_count: number;
  findings_count: number;
};

export type ValidationSignal = {
  signal_id: string;
  signal_type: string;
  analyzer_id: string;
  metric_name: string;
  service?: string;
  severity: string;
  confidence: number;
  start_time: string;
  end_time: string;
  summary: string;
  evidence: Record<string, unknown>;
};

export type ValidationFinding = {
  metric_name: string;
  service?: string;
  title: string;
  summary: string;
  category: string;
  health_status: string;
  importance_score: number;
  investigation_priority: number;
  signal_ids: string[];
  comparison_json: Record<string, unknown>;
};

export type CsvValidationResult = {
  provider: string;
  source_type: string;
  analyzer_id: string;
  service: string;
  metric_name: string;
  sample_count: number;
  normalized_preview: Array<Record<string, unknown>>;
  signals: ValidationSignal[];
  findings: ValidationFinding[];
  analyzer_selection_mode?: string;
  analyzer_routing?: Array<Record<string, unknown>>;
  executed_analyzers?: string[];
};

export type CsvAnalyzerRoutingDecision = {
  analyzer_id?: string;
  display_name?: string;
  recommendation?: string;
  final_score?: number;
  eligible?: boolean;
  explanation?: string;
  routing_reason?: string;
  reasons?: string[];
  warnings?: string[];
};

export type MetricSample = {
  service: string;
  metric_name: string;
  analysis_run_id?: string | null;
  sample_count: number;
  start_time: string;
  end_time: string;
  sampling_interval_seconds?: number | null;
  missing_ratio: number;
  min_value?: number | null;
  max_value?: number | null;
  mean_value?: number | null;
  stddev_value?: number | null;
};

export type MetricProfile = {
  sample_count: number;
  start_time: string;
  end_time: string;
  sampling_interval_seconds?: number | null;
  regular_sampling: boolean;
  missing_ratio: number;
  duplicate_timestamps: number;
  constant_value_ratio: number;
  mean: number;
  stddev: number;
  minimum: number;
  maximum: number;
  variance: number;
  trend_slope: number;
  trend_strength: number;
  autocorrelation?: number | null;
  seasonality_strength: number;
  sparsity: number;
  metric_behavior: string;
};

export type AnalyzerRecommendation = {
  analyzer_id: string;
  display_name: string;
  recommendation: string;
  fitness_score: number;
  decision_confidence: number;
  summary: string;
  evidence: Record<string, unknown>;
  requirements: string[];
  warnings: string[];
  parameters_tested: Record<string, unknown>;
};

export type MetricAnalyzerRecommendation = {
  sample: MetricSample;
  profile: MetricProfile;
  recommendations: AnalyzerRecommendation[];
};

export type TimeValuePoint = {
  timestamp: string;
  value: number;
};

export type MetricContext = {
  metric_id?: string | null;
  sample_id?: number | null;
  metric_name: string;
  metric_description: string;
  metric_type?: string | null;
  provider?: string | null;
  unit?: string | null;
  operational_purpose: string;
  use_cases: string[];
  operational_questions: string[];
  example_values: TimeValuePoint[];
  additional_notes?: string | null;
};

export type AnalyzerRecommendationChatRequest = {
  conversation_id?: string | null;
  message: string;
  metric_context: MetricContext;
  options: {
    include_vector_discovery: boolean;
    run_sample_evaluation: boolean;
    requested_analyzers?: string[] | null;
  };
};

export type AnalyzerRecommendationChatResponse = {
  conversation_id: string;
  evaluation_id?: number | null;
  response_type: string;
  recommendation_mode: 'preliminary' | 'evaluated';
  assistant_message: {
    headline: string;
    summary: string;
    context_used: string[];
    next_action: string;
  };
  recommendations: AnalyzerRecommendation[];
  suggested_questions: string[];
  context_hash: string;
  context_version: number;
  normalized_goals: Array<{ goal_id: string; display_name: string; source_text: string }>;
  stale: boolean;
};

export type MemoryChatRequest = {
  conversation_id?: string | null;
  message: string;
  case_id?: number | null;
  top_k?: number;
  minimum_score?: number;
  same_service_only?: boolean;
};

export type MemoryChatSource = {
  case_id: number;
  title: string;
  similarity_score: number;
  service?: string | null;
  metric_name?: string | null;
  category?: string | null;
  case_status: string;
  root_cause_summary?: string | null;
  outcome_summary?: string | null;
};

export type MemoryChatResponse = {
  conversation_id: string;
  answer: string;
  limitations: string[];
  suggested_questions: string[];
  sources: MemoryChatSource[];
};

export type AssistantChatRequest = {
  conversation_id?: string | null;
  message: string;
  case_id?: number | null;
  top_k?: number;
  minimum_score?: number;
  same_service_only?: boolean;
};

export type AssistantSource = {
  source_type: string;
  title: string;
  score: number;
  reference: string;
  service?: string | null;
  metric_name?: string | null;
  summary?: string | null;
};

export type AssistantEvidenceGroup = {
  source_type: string;
  label: string;
  count: number;
  sources: AssistantSource[];
};

export type AssistantChatResponse = {
  conversation_id: string;
  intent: string;
  routes?: string[];
  knowledge_used?: string[];
  answer: string;
  limitations: string[];
  suggested_questions: string[];
  sources: AssistantSource[];
  evidence_groups?: AssistantEvidenceGroup[];
};

export * from './benchmark';

