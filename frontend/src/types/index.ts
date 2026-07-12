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
