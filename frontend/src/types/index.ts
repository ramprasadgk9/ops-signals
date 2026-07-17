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

export type AnalysisRun = {
  id: string;
  source_type: string;
  provider: string;
  service: string;
  metric_name: string;
  start_time: string;
  end_time: string;
  sample_count: number;
  status: string;
  created_at: string;
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
  provider: string;
  source_type: string;
  service: string;
  metric_name: string;
  sample_count: number;
  findings_count: number;
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
