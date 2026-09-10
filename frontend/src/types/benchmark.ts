export type BenchmarkScenarioDescriptor = {
  id: string;
  title: string;
  entity: string;
  root_cause: string;
  fault_window: {
    start?: string;
    end?: string;
  };
  key_evidence: {
    metrics?: string[];
    signals?: string[];
  };
  has_metrics: boolean;
  has_events: boolean;
};

export type BenchmarkJudgeConsensus = {
  judge_id: string;
  attribution: number;
  grounding: number;
  actionability: number;
  justification: string;
};

export type BenchmarkJudgeScore = {
  judge_id: string;
  attribution: number;
  grounding: number;
  actionability: number;
  justification: string;
};

export type BenchmarkJudgeResult = {
  consensus: BenchmarkJudgeConsensus;
  scores: BenchmarkJudgeScore[];
  inter_rater_agreement?: {
    fleiss_kappa?: number | null;
    krippendorff_alpha?: number | null;
    interpretation?: string;
  };
};

export type TrajectoryTurn = {
  turn: number;
  thought?: string;
  action?: string;
  tool?: string;
  input?: Record<string, unknown> | string;
  observation?: string | Record<string, unknown>;
  output?: string;
};

export type BenchmarkSystemRunResult = {
  runner_id: string;
  status: 'SUCCESS' | 'PARTIAL' | 'FAILED' | string;
  entity: string | null;
  root_cause: string;
  summary_text?: string;
  window_iou: number;
  evidence_f1: number;
  composite_score: number;
  tokens: number;
  cost_usd: number;
  execution_time_seconds: number;
  metadata?: {
    model_id?: string;
    provider?: string;
    input_tokens?: number;
    output_tokens?: number;
    trajectory_turns?: number;
    trajectory?: TrajectoryTurn[];
    executed_analyzers?: string[];
    finding_count?: number;
    signal_count?: number;
    behavior_finding_count?: number;
  };
  judge?: BenchmarkJudgeResult | null;
};

export type BenchmarkScenarioResult = {
  scenario: string;
  ground_truth: {
    scenario_id?: string;
    entity?: string;
    root_cause?: string;
    secondary_symptoms?: string[];
    fault_window?: {
      start?: string;
      end?: string;
    };
    key_evidence?: {
      metrics?: string[];
      signals?: string[];
    };
  };
  iam?: BenchmarkSystemRunResult;
  baseline_a?: BenchmarkSystemRunResult;
  baseline_b?: BenchmarkSystemRunResult;
};

export type BenchmarkSummarySystem = {
  runs: number;
  success_count: number;
  partial_count: number;
  failed_count: number;
  success_rate_pct: number;
  total_tokens: number;
  total_cost_usd: number;
  avg_latency_s: number;
  avg_evidence_f1: number;
  avg_judge_attribution: number;
  avg_judge_grounding: number;
  avg_judge_actionability: number;
};

export type BenchmarkParetoSummary = {
  token_reduction_vs_a_pct: number;
  token_reduction_vs_b_pct: number;
  cost_reduction_pct: number;
  latency_speedup_vs_a_x: number;
  iam_cost_per_incident: string;
  iam_token_usage: number;
};

export type BenchmarkReportResponse = {
  report_path: string;
  generated_at: string;
  scenarios: BenchmarkScenarioResult[];
  summary: {
    iam: BenchmarkSummarySystem;
    baseline_a: BenchmarkSummarySystem;
    baseline_b: BenchmarkSummarySystem;
    pareto: BenchmarkParetoSummary;
  };
};

export type BenchmarkRunRequestPayload = {
  scenarios?: string[];
  provider?: 'mock' | 'gemini' | 'openai' | 'openrouter';
  model_id?: string;
  judge_provider?: string;
};
