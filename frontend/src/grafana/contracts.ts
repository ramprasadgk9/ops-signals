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
