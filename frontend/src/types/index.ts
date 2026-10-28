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
  source_file?: string | null;
};

/** One analysis run as a draft rule would have judged it (POST /api/behavior-definitions/history-preview). */
export type HistoryRun = {
  analysis_run_id: string;
  at: string | null;
  matched: boolean;
  missing_inputs: string[];
  blocked_by: string[];
  /** Each condition with the value it was checked against; empty when an input had no signal. */
  conditions: Array<{ group: string; fact: string; operator: string; value: unknown; passed: boolean; actual: unknown }>;
  confidence: number | null;
  changes: Array<{ alias: string; signed_change_percent: number | null }>;
  overlap_minutes: number | null;
  start: string | null;
  end: string | null;
};

export type HistoryPreview = {
  service: string;
  since: string;
  verdict: 'fired' | 'never' | 'cant_check' | 'no_runs';
  reason: string | null;
  runs_checked: number;
  runs_judged: number;
  runs_matched: number;
  conditions: Array<{ group: string; fact: string; operator: string; value: unknown; passed_runs: number }>;
  inputs: Array<{ alias: string; metric_name: string; analyzers: string[]; runs_with_signals: number }>;
  runs: HistoryRun[];
  series: Array<{ alias: string; metric_name: string; points: Array<[string, number]> }>;
  series_truncated: boolean;
};

/** A signal of a catalog template: what to look for, and words to find the user's metric by. */
export type CatalogSignal = {
  alias: string;
  label: string;
  shape: 'rising' | 'falling' | 'unusual';
  metric_hint: string;
  keywords: string[];
  analyzers: string[];
};

/** A known pattern (config/behavior_patterns_catalog.yml): a shipped rule with its proof, or a template. */
export type CatalogPattern = {
  key: string;
  rule: string | null;
  name: string;
  area?: string | null;
  meaning: string;
  why: string;
  check_first: string;
  proof: 'tested' | 'shipped' | 'common';
  scenarios: string[];
  signals: CatalogSignal[];
  draft: Record<string, unknown> | null;
};

export type FactDescriptor = {
  key: string;
  description: string;
  example: unknown;
};

export type BehaviorConditionInput = {
  fact: string;
  operator: string;
  value: unknown;
};

export type BehaviorDefinitionDraft = {
  id: string;
  enabled?: boolean;
  version?: number;
  title: string;
  description?: string;
  scope?: Record<string, unknown>;
  inputs: Array<{ alias: string; metric_name: string; analyzers?: string[] }>;
  conditions: Record<string, BehaviorConditionInput[]>;
  correlation?: Record<string, unknown>;
  output: {
    category?: string;
    severity?: string;
    title: string;
    summary?: string;
    evidence?: string[];
  };
};

export type ValidationResult = {
  valid: boolean;
  errors: string[];
  warnings: string[];
};

export type SaveDraftResult = {
  saved: boolean;
  pack_file: string;
  validation: ValidationResult;
};

export type BehaviorPatternSuggestion = {
  id: number;
  service?: string | null;
  metric_a: string;
  metric_b: string;
  co_occurrence_count: number;
  metric_a_occasions: number;
  metric_b_occasions: number;
  correlation_strength: number;
  sample_analysis_run_ids: string[];
  draft_definition_json: Record<string, unknown>;
  draft_yaml_text: string;
  status: string;
  created_at: string;
};

export type BehaviorFinding = {
  id: number;
  behavior_id: string;
  definition_id: string;
  definition_version: number;
  title: string;
  summary: string;
  /** Plain-words rewrite of the facts, written by the backend on first read; null until then. */
  ai_explanation?: string | null;
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
  occurrence_count: number;
  last_seen_at: string;
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
  cluster?: string | null;
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
  /** External cluster label (Mimir/Thanos multi-cluster); null for single-cluster data. */
  cluster?: string | null;
  /** Prometheus connection (Mimir tenant) the finding's run queried; null for CSV/OTLP runs. */
  connection_id?: string | null;
  /** Where its data came from: 'prometheus', 'otlp' or 'csv'; null when its run isn't known. */
  source?: string | null;
  title: string;
  summary: string;
  ai_summary?: string | null;
  category: string;
  health_status: string;
  importance_score: number;
  investigation_priority: number;
  signal_ids: string[];
  comparison_json: Record<string, unknown>;
  analysis_run_id?: string;
  created_at?: string;
  /** When the problem happened, and whether it was still going on at the end of the analyzed data. */
  event_start?: string | null;
  event_end?: string | null;
  ongoing?: boolean | null;
  /** The first finding of the same problem, seen by an earlier run; null when this one is the first. */
  problem_id?: number | null;
  /** Deploys and other change events near the finding's change; read with utils/findingChanges. */
  changes?: unknown;
  /** How much to trust it (backend services/finding_trust.py); read with utils/findingTrust. */
  trust?: FindingTrust | null;
  /** Plain-words wording for the card (backend services/finding_plain.py); read with utils/findingPlain. */
  plain?: FindingPlain | null;
  /** Per-service analyzer settings it was made with; null on the default settings. Read with utils/customSettings. */
  custom_settings?: FindingCustomSettings | null;
};

export type FindingCustomSettings = {
  settings: Array<{ analyzer_id: string; analyzer: string; path: string; label: string; value: unknown; default: unknown }>;
  overrides: Array<{ id: string; file?: string; reason?: string }>;
};

export type FindingPlainBadge = 'worse' | 'better' | 'changed' | 'gap' | 'noise' | 'blip';

/** Text fields hold time markers, [[time:ISO]], that utils/findingPlain shows in the reader's time zone. */
export type FindingPlain = {
  kind: string;
  badge: FindingPlainBadge;
  badge_label: string;
  headline: string;
  what: string;
  why?: string | null;
  check?: string | null;
  change_time?: string | null;
  /** Other metrics of the same service that changed at the same moment. */
  related?: Array<{ finding_id: number | null; text: string }>;
  /** How the finding stands against its service's target ("Above your 1% target since ..."). */
  target?: string | null;
  /** What the service does, and how important it is, from the `services` section of the wording file. */
  service_about?: string | null;
  service_importance?: 'critical' | 'normal' | 'low' | null;
  service_importance_label?: string | null;
};

/** GET /api/findings/{id}/ai-wording: lines the AI provider wrote for this finding's details
 * (backend/app/services/finding_ai_wording.py). A null line keeps the template; `reason` says why
 * nothing is available: ai_off (no AI provider), no_plain or failed. */
export type FindingAIWording = {
  available: boolean;
  reason?: 'ai_off' | 'no_plain' | 'failed' | null;
  /** Replaces the template's Why it matters. */
  why?: string | null;
  /** One more thing to check, after the template's What to check. */
  check_extra?: string | null;
  /** One more sentence after the first Happened with line. */
  related_extra?: string | null;
  model?: string | null;
};

/** One fact a case draft was written from (backend/app/services/case_ai_drafts.py). */
export type CaseDraftSource = {
  kind: 'finding' | 'deploy' | 'ticket' | 'note' | 'ticket_comment' | 'similar_case' | 'root_cause' | 'corrective_action' | 'timeline';
  label: string;
  detail?: string | null;
};

/** "Draft from case" on the Root Cause tab. Never saved; `reason_code` says why there is none. */
export type CaseRcaDraft = {
  available: boolean;
  draft?: string | null;
  based_on_similar_cases?: number[];
  sources?: CaseDraftSource[];
  reason?: string | null;
  reason_code?: 'ai_off' | 'not_enough' | 'failed' | null;
};

/** "Draft from case" on the Resolution tab: `draft` is the outcome summary. */
export type CaseResolutionDraft = Omit<CaseRcaDraft, 'based_on_similar_cases'> & {
  corrective_action?: string | null;
};

/** "Draft write-up" on Publish Knowledge: labelled paragraphs (Summary, Likely cause...). */
export type CaseWriteupDraft = Omit<CaseRcaDraft, 'based_on_similar_cases'>;

export type CaseTimelineEvent = {
  time: string;
  kind: 'deploy' | 'finding' | 'opened' | 'ticket' | 'note' | 'ticket_comment' | 'resolved';
  text: string;
  who?: string | null;
};

/** Publish Knowledge: what happened, built from the case (no AI), and the text memory indexes. */
export type CaseTimeline = {
  events: CaseTimelineEvent[];
  time_to_fix_minutes?: number | null;
  memory_text: string;
};

export type FindingVerdict = 'real_problem' | 'expected_change' | 'not_a_problem';

export type FindingTrustGroup = 'data_problem' | 'level_change_agree' | 'level_change_single' | 'spike' | 'pattern';

export type FindingTrust = {
  group: FindingTrustGroup;
  tier: 'needs_attention' | 'context';
  badge: 'strong' | 'moderate' | 'data_problem' | 'team_confirmed' | null;
  /** Set when this service's own answers moved the group off its tested list. */
  moved?: 'up' | 'down' | null;
  checks: string[];
  /** Tested numbers from public benchmark data; null when the group wasn't tested enough. */
  tested: {
    real: number;
    checked: number;
    random: number;
    dataset: string;
    data_kind: string;
    /** Whether this finding's metric is like the ones tested (CPU, memory, latency). */
    fits_metric: boolean;
    measured_at?: string | null;
  } | null;
  /** This service's own "Was this real?" answers on findings in the same group; per metric (`scope`
   * "metric") when the finding has no service label. An older backend sends no scope. */
  service: { real: number; answered: number; min_answers: number; scope?: 'service' | 'metric' };
  your_answer: FindingVerdict | null;
  /** Who gave that answer, when it came through Grafana, and when. */
  answered_by?: string | null;
  answered_at?: string | null;
  /** Made with per-service analyzer settings: `tested` is null because it was measured with the defaults. */
  custom_settings?: boolean;
};

export type OperationalCase = {
  id: number;
  finding_id: number | null;
  behavior_finding_id?: number | null;
  analysis_run_id: string;
  case_title: string;
  case_status: string;
  finding_snapshot: Finding;
  investigation_status: string;
  investigation_notes: Array<{ timestamp?: string; note: string; source?: string }>;
  root_cause_status: string;
  root_cause_summary?: string;
  root_cause_confidence?: number;
  root_cause_verified: boolean;
  corrective_action?: string;
  outcome_status: string;
  outcome_summary?: string;
  memory_status: string;
  /** The Grafana user who opened it, and who closed it; absent when not done through Grafana. */
  created_by?: string | null;
  resolved_by?: string | null;
  /** The saved write-up from Publish Knowledge, published to memory with the case. */
  writeup?: string | null;
  created_at: string;
  updated_at: string;
  resolved_at?: string;
  /** "detected" for cases Ops Signals opened; otherwise the tool an imported case came from. */
  source?: string;
  source_id?: string | null;
  source_url?: string | null;
  import_batch_id?: string | null;
};

/** A past case that resembles something current: a finding ("Seen before?") or a case (Similar Cases). */
export type PastCaseMatch = {
  case_id: number;
  title: string;
  similarity_score: number;
  strength?: 'strong' | 'possible' | string;
  same_service?: boolean;
  service?: string | null;
  metric_name?: string | null;
  origin?: 'detected' | 'imported' | string;
  source?: string | null;
  source_id?: string | null;
  source_url?: string | null;
  case_status?: string;
  rca_verified?: boolean;
  root_cause_summary?: string | null;
  corrective_action?: string | null;
  outcome_summary?: string | null;
  /** Near-copies folded under this match (same service, symptom, cause and fix). */
  more_like_this?: PastCaseMatch[];
};

/** Did a fix hold? Inferred: the same symptom didn't come back on the service within 30 days. */
export type FixOutcome = {
  status: 'held' | 'came_back' | 'too_early' | 'not_fixed' | 'unknown';
  label: string;
  came_back_case_id?: number | null;
  came_back_after_days?: number | null;
};

export type SuggestedFix = {
  fix: string;
  root_cause?: string | null;
  held: number;
  came_back: number;
  too_early: number;
  label: string;
  verified: number;
  sources: { case_id: number; title: string; service?: string | null; corrective_action: string; outcome: FixOutcome }[];
};

export type SuggestedFixesResponse = {
  finding_id: number;
  available: boolean;
  reason?: string | null;
  based_on_cases: number;
  fixes: SuggestedFix[];
};

export type RunbookDraft = {
  available: boolean;
  draft?: string | null;
  reason?: string | null;
  based_on_cases: number[];
};

export type SameFixResponse = {
  case_id: number;
  available: boolean;
  reason?: string | null;
  outcome?: FixOutcome | null;
  matches: {
    case_id: number;
    title: string;
    service?: string | null;
    similarity_score: number;
    root_cause_summary?: string | null;
    corrective_action?: string | null;
    rca_verified: boolean;
    outcome: FixOutcome;
  }[];
};

/** How familiar a finding or case is, read off its past-case matches (backend/app/memory/novelty.py). */
export type Novelty = {
  level: 'new' | 'new_on_service' | 'seen_before' | 'recurring';
  label: string;
  explanation: string;
  matching_cases: number;
  all_matching_cases: number;
  best_score?: number | null;
};

/** A part of the finding details drawer that a card can open it at. */
export type FindingDetailsSection = 'seen-before' | 'came-back';

/** The problem is back within 30 days of a past case on the same service being fixed: that fix
 * didn't stick (backend/app/memory/fix_came_back.py). */
export type CameBackAfterFix = {
  case_id: number;
  title: string;
  fixed_at: string;
  days: number;
  fix: string;
  still_open?: string | null;
};

/** Both directions for a case: back after an earlier fix, and whether its own fix held. */
export type CaseFixCameBack = {
  case_id: number;
  available: boolean;
  reason?: string | null;
  came_back?: CameBackAfterFix | null;
  fix_outcome?: FixOutcome | null;
};

/** "Why might it not have held?" (AI, never saved). */
export type FixCameBackWhy = {
  available: boolean;
  reasons: string[];
  sources?: CaseDraftSource[];
  reason?: string | null;
  reason_code?: 'ai_off' | 'not_enough' | 'failed' | null;
};

export type SeenBeforeResponse = {
  finding_id: number;
  available: boolean;
  reason?: string | null;
  service?: string | null;
  matches: PastCaseMatch[];
  novelty?: Novelty | null;
  came_back?: CameBackAfterFix | null;
};

export type SimilarCasesResponse = {
  source_case_id: number;
  matches: PastCaseMatch[];
  novelty?: Novelty | null;
};

export type RecurringProblem = {
  name: string;
  named_by: 'ai' | 'central_case';
  central_case_id: number;
  occurrences: number;
  services: string[];
  first_seen?: string | null;
  last_seen?: string | null;
  verified_root_causes: number;
  open_cases: number;
  causes: { case_id: number; root_cause: string; fix?: string | null; verified: boolean }[];
  cases: {
    case_id: number;
    title: string;
    service?: string | null;
    created_at?: string | null;
    origin: string;
    case_status: string;
    rca_verified: boolean;
    similarity_to_central: number;
  }[];
};

export type CoverageStatus = 'detected' | 'flagged_other' | 'missed' | 'not_watched' | 'unknown';

/** Which imported past incidents Ops Signals detected while they happened (backend/app/memory/coverage.py). */
export type CoverageReport = {
  available: boolean;
  reason?: string | null;
  window_days: number;
  incidents_considered: number;
  counts: Partial<Record<CoverageStatus, number>>;
  services: { service: string; counts: Partial<Record<CoverageStatus, number>> }[];
  incidents: {
    case_id: number;
    title: string;
    service?: string | null;
    started_at?: string | null;
    status: CoverageStatus;
    label: string;
    explanation: string;
    evidence: { kind: 'finding' | 'behavior'; id: number; title: string; similarity: number; at?: string | null }[];
    seen_elsewhere: number;
    seen_elsewhere_case_id?: number | null;
    seen_elsewhere_at?: string | null;
  }[];
};

export type RecurringProblemsResponse = {
  available: boolean;
  reason?: string | null;
  window_days: number;
  min_occurrences: number;
  group_by: 'symptom' | 'cause';
  group_similarity: number;
  cases_considered: number;
  sampled: boolean;
  problems: RecurringProblem[];
};

export type CaseImportProfile = {
  id: string;
  label: string;
  kind: 'csv' | 'markdown';
  default_source: string;
  checklist: string[];
};

export type CaseImportProfiles = {
  profiles: CaseImportProfile[];
  fields: string[];
  required_fields: string[];
  templates: string[];
};

export type CaseImportSettings = {
  profile?: string;
  source?: string;
  column_map?: Record<string, string>;
  service_aliases?: Record<string, string>;
};

export type CaseImportCounts = {
  new: number;
  updated: number;
  unchanged: number;
  skipped: number;
  duplicate_rows: number;
};

export type CaseImportRecord = {
  ref: string;
  source: string;
  source_id: string | null;
  title: string;
  service: string;
  started_at: string | null;
  action: 'new' | 'updated' | 'unchanged' | 'skipped' | 'duplicate';
  problems: string[];
  redactions: number;
  case_id: number | null;
};

export type CaseImportPreview = {
  file_profiles: Record<string, string>;
  warnings: string[];
  counts: CaseImportCounts;
  redactions: number;
  records: CaseImportRecord[];
};

export type CaseImportResult = CaseImportPreview & {
  batch_id: string;
  indexed: number;
  index_failed: number;
};

export type CaseImportBatch = {
  id: string;
  sources: string[];
  file_profiles: Record<string, string>;
  counts: Partial<CaseImportCounts>;
  indexed: number;
  status: 'running' | 'completed' | 'undone';
  created_at: string;
  undone_at: string | null;
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
  window: '6h' | '24h' | '7d';
  active_findings: number;
  /** active_findings split: problems that need attention, and the rest (context). */
  attention_findings?: number;
  context_findings?: number;
  open_cases: number;
  behavior_changes: number;
  impacted_services: number;
  memory_items: number;
  severity_trend: SeverityTrendPoint[];
  category_breakdown: CategoryBreakdown[];
};

/** GET /api/overview/handoff: for the next person on call (backend/app/services/shift_handoff.py). */
export type HandoffWatchItem = {
  kind: 'case' | 'finding';
  title: string;
  severity?: string | null;
  service?: string | null;
  metric_name?: string | null;
  since?: string | null;
  case_id?: number | null;
  finding_id?: number | null;
  case_status?: string | null;
  deploy_version?: string | null;
  deploy_at?: string | null;
  /** Plain words: "open 8 hours, started after deploy v2.3, critical". */
  reason: string;
};

export type ShiftHandoff = {
  generated_at: string;
  hours: number;
  since: string;
  new_findings: number;
  cases_opened: number;
  cases_resolved: number;
  cases_still_open: number;
  watch: HandoffWatchItem[];
  /** The note without AI, ready to paste. */
  summary: string;
};

/** POST /api/overview/handoff/note: the same handoff written up by AI. */
export type ShiftHandoffNote = {
  available: boolean;
  note?: string | null;
  reason?: string | null;
  reason_code?: 'ai_off' | 'failed' | null;
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
  is_default?: boolean;
  match_labels?: Record<string, string>;
  /** The label that tells clusters apart on this connection; null when turned off. */
  cluster_label?: string | null;
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
  /** Why it ran or didn't; see intelligence/analyzer_selection.py RUN_REASON_TEXT. Absent on older runs. */
  run_reason?: string | null;
  shapes?: string[];
  missing_library?: string | null;
  /** Whether its signals are part of a finding; null when it didn't run or the run predates this. */
  in_finding?: boolean | null;
  /** What the analyzer looks for, in plain words, from its registration. */
  description?: string | null;
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
  requested_interval?: string;
  interval?: string;
  warnings?: string[];
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
  plain?: FindingPlain | null;
};

export type CsvValidationResult = {
  provider: string;
  source_type: string;
  analyzer_id: string;
  service: string;
  metric_name: string;
  sample_count: number;
  requested_interval?: string;
  interval?: string;
  warnings?: string[];
  normalized_preview: Array<Record<string, unknown>>;
  signals: ValidationSignal[];
  findings: ValidationFinding[];
  analyzer_selection_mode?: string;
  analyzer_routing?: Array<Record<string, unknown>>;
  executed_analyzers?: string[];
  analyzer_executions?: AnalyzerExecution[];
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
  parameters_tested?: { detected_profiles?: string[] } | null;
};

export type MetricSample = {
  service: string;
  metric_name: string;
  analysis_run_id?: string | null;
  sample_count: number;
  start_time: string;
  end_time: string;
  sampling_interval_seconds?: number | null;
  missing_ratio?: number | null;
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

export type AIAnalyzerPick = {
  analyzer_id: string;
  recommendation: 'recommended' | 'optional' | 'not_recommended';
  rank?: number | null;
  confidence: number;
  reason: string;
};

// Independent second opinion from an optional LLM advisor, computed alongside - never instead of -
// the deterministic `recommendations` above. available=false whenever AI is off or the advisor
// call fails; the deterministic recommendations remain complete and correct either way.
export type AIAnalyzerOpinion = {
  available: boolean;
  best_analyzer_id?: string | null;
  rationale?: string | null;
  recommended: AIAnalyzerPick[];
  not_recommended: AIAnalyzerPick[];
  caveats: string[];
  diverges_from_router: boolean;
  router_top_analyzer_id?: string | null;
  unavailable_reason?: string | null;
};

export type MetricAnalyzerRecommendation = {
  sample: MetricSample;
  profile: MetricProfile;
  recommendations: AnalyzerRecommendation[];
  ai_opinion: AIAnalyzerOpinion;
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
  ai_opinion: AIAnalyzerOpinion;
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

export type AlertContextOutcome = {
  outcome_status: string;
  root_cause_category?: string | null;
  resolution_summary?: string | null;
  confirmed_analyzers: string[];
  rejected_analyzers: string[];
  case_id: number;
  resolved_at?: string | null;
  created_at: string;
};

export type AlertContextSimilarCase = {
  case_id: number;
  similarity_score: number;
  title: string;
  case_status: string;
  outcome_status?: string | null;
  root_cause_summary?: string | null;
  corrective_action?: string | null;
  outcome_summary?: string | null;
  origin?: 'detected' | 'imported' | string;
  source?: string | null;
  source_id?: string | null;
  reference: string;
};

export type AlertContextHistory = {
  total_prior_occurrences: number;
  confirmed: number;
  rejected: number;
  partially_confirmed: number;
  inconclusive: number;
  confirmed_rate?: number | null;
  most_common_root_cause?: string | null;
  last_seen_at?: string | null;
};

export type AlertContextRawActivity = {
  finding_count: number;
  behavior_count: number;
  total_occurrences: number;
  most_recent_at?: string | null;
  recent_titles: string[];
  ai_summary?: string | null;
};

export type AlertContextResponse = {
  service?: string | null;
  metric_name: string;
  history: AlertContextHistory;
  exact_match_outcomes: AlertContextOutcome[];
  similar_cases: AlertContextSimilarCase[];
  raw_activity: AlertContextRawActivity;
  recommendation: 'likely_real' | 'likely_noise' | 'insufficient_history';
  recommendation_basis: string;
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
  source_path?: string | null;
  section?: string | null;
  quote?: string | null;
};

export type KnowledgeReindexResult = {
  added: string[];
  changed: string[];
  removed: string[];
  unchanged_documents: number;
  chunks_embedded: number;
  forced: boolean;
  started_at: string;
  duration_ms: number;
};

export type StarterQuestions = {
  has_data: boolean;
  questions: string[];
};

export type KnowledgeChanges = {
  added: string[];
  changed: string[];
  removed: string[];
};

export type KnowledgeStatus = {
  collection_exists: boolean;
  vector_count: number;
  document_count: number;
  pending_changes: KnowledgeChanges | null;
  docs_authoring_enabled: boolean;
  last_bootstrap: KnowledgeReindexResult | null;
};

export type AssistantFeedbackReason = 'wrong_section' | 'missing_step' | 'outdated' | 'not_in_docs';

export type AssistantFeedbackCreate = {
  question: string;
  helpful: boolean;
  reason?: AssistantFeedbackReason | null;
  answer?: string | null;
  conversation_id?: string | null;
  ai_synthesis_used?: boolean;
  cited?: string[];
};

export type AssistantFeedbackUpdate = {
  reason?: AssistantFeedbackReason | null;
  status?: 'open' | 'added_as_test' | 'dismissed' | null;
};

export type AssistantFeedback = {
  id: number;
  question: string;
  helpful: boolean;
  reason: AssistantFeedbackReason | null;
  status: 'open' | 'added_as_test' | 'dismissed';
  created_at: string;
};

export type FlaggedQuestion = {
  question: string;
  count: number;
  reasons: Record<string, number>;
  cited: string[];
  feedback_ids: number[];
  last_flagged_at: string;
};

export type DocCoverage = {
  source_path: string;
  title: string;
  section_count: number;
  test_count: number;
  untested_sections: string[];
  recently: 'added' | 'changed' | null;
};

export type DocsCoverage = {
  golden_available: boolean;
  total_docs: number;
  covered_docs: number;
  docs: DocCoverage[];
};

export type DraftQuestion = {
  source_path: string;
  section: string;
  question: string;
  contains: string[];
  drafted_by: string;
};

export type DocQuestionEvaluation = {
  cited_expected: boolean;
  rank: number | null;
  cited: Array<{ source_path: string | null; section: string | null; reference: string; quote: string | null }>;
  answer: string;
  ai_synthesis_used: boolean;
};

export type NewDocTest = {
  question: string;
  source_path: string;
  section?: string | null;
  contains: string[];
  known_gap: boolean;
  feedback_ids?: number[];
};

export type SaveDocTestsResult = {
  saved_ids: string[];
  yaml: string;
  path: string;
  written: boolean;
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
  ai_synthesis_used?: boolean;
  limitations: string[];
  suggested_questions: string[];
  sources: AssistantSource[];
  evidence_groups?: AssistantEvidenceGroup[];
};

export type AlertItem = {
  id: number;
  source: string;
  alert_name: string;
  status: 'firing' | 'resolved' | string;
  service: string | null;
  severity: string | null;
  summary: string;
  starts_at: string;
  ends_at: string | null;
  received_at: string;
  labels: Record<string, string>;
  generator_url: string | null;
  analysis_status: string | null;
  recommendation: string | null;
  notify_status: string | null;
  finding_id: number | null;
  case_id: number | null;
  /** Where deploy matching started from (backend/app/alerts/timing.py); null until enriched. */
  timing?: AlertTiming | null;
  changes?: AlertChange[];
  change_window_before_minutes?: number | null;
  service_has_change_events?: boolean | null;
  /** Ops Signals also looks for deploys in Prometheus (docs/deploy-discovery.md). */
  deploy_discovery?: boolean;
  /** The finding's pod breakdown (see utils/findingBreakdown.ts). */
  breakdown?: Record<string, unknown> | null;
};

export type AlertTiming = {
  basis: 'step_change' | 'spike' | 'trend' | 'alert_time' | string;
  time: string | null;
  analyzer_id: string | null;
  trend_direction: 'upward' | 'downward' | string | null;
};

export type AlertChange = {
  id: number | null;
  event_type: string | null;
  version: string | null;
  description: string | null;
  author: string | null;
  url: string | null;
  timestamp: string | null;
  /** Positive: the change came before the start time (or the alert, when there is no start time). */
  minutes_before_anchor: number | null;
  /** Cluster the change went to; absent or null when it went to every cluster. */
  cluster?: string | null;
  /** Who reported it: CI's own source, or `ops-signals:...` for a deploy found in Prometheus. */
  source?: string | null;
};

export type AlertReceipt = {
  accepted: number;
  duplicates: number;
  resolved: number;
  disabled: boolean;
  enrichment_ids: number[];
};

export type AlertListParams = {
  status?: 'firing' | 'resolved';
  service?: string;
  finding_id?: number;
  since?: string;
  limit?: number;
};

export type IngestionStatus = {
  generated_at: string;
  has_any_data: boolean;
  sources: {
    otlp: { endpoint_path: string; last_received_at: string | null };
    alertmanager: {
      endpoint_path: string;
      enabled: boolean;
      token_required: boolean;
      last_received_at: string | null;
      received_24h: number;
    };
    prometheus: {
      configured: boolean;
      /** Without any user:password@ part. */
      url?: string | null;
      /** null when not configured. */
      reachable?: boolean | null;
      scheduled_policies?: number;
      alert_enrichment_enabled?: boolean;
      /** One per configured connection; `reachable` above is true while any of them answers. */
      connections?: Array<{ id: string; name: string; configured: boolean; url?: string | null; reachable?: boolean | null }>;
    };
    /** Deploys and other change events sent to POST /api/events. */
    events?: {
      endpoint_path: string;
      token_required: boolean;
      last_received_at: string | null;
      received_24h: number;
      last_event: { service: string; type: string; version: string | null; env: string | null; timestamp: string } | null;
    };
    /** Read by the metric usage check. */
    grafana?: {
      configured: boolean;
      /** Without any user:password@ part. */
      url: string | null;
      /** null when not configured. */
      reachable: boolean | null;
    };
  };
  /** What the connected sources turn on (backend/app/capabilities/availability.py). */
  features?: FeatureAvailability[];
};

export type SourceId = 'otlp' | 'prometheus' | 'alertmanager' | 'grafana' | 'events';

export type FeatureAvailability = {
  id: string;
  label: string;
  state: 'on' | 'partly' | 'off';
  /** Sources to connect: the missing requirements when off, the missing extras when partly. */
  missing: SourceId[];
  detail: string | null;
  /** The feature's own requirements (absent from older backends). */
  needs?: SourceId[];
  better_with?: SourceId[];
};

export type OtlpStatus = {
  endpoint_path: string;
  points_received_total: number;
  points_rejected_total: Record<string, number>;
  backlog_size: number;
  last_analysis_cycle_duration_seconds: number;
  last_analysis_cycle_groups_processed: number;
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
  promoted_to_note?: boolean;
  auto_promoted?: boolean;
};

export type CaseNotePromoteResult = {
  success: boolean;
  case_id: number;
  event_id: number;
  note: string;
  investigation_status: string;
  already_promoted: boolean;
  auto_promoted?: boolean;
};

export type CommentTriageResult = {
  case_id: number;
  evaluated_count: number;
  promoted_count: number;
  promoted_notes: string[];
};

export type AmbiguousResolutionPayload = {
  action: 'check_again' | 'link_existing' | 'force_create_new';
  remote_key?: string;
};

/** GET /api/integrations/ticketing/status: whether ticketing is on, so ticket actions show only where they can work. */
export type TicketingStatus = {
  enabled: boolean;
  provider: string;
  provider_configured: boolean;
  webhook_secret_configured: boolean;
};

export type WebhookInfoView = {
  provider: string;
  webhook_url: string;
  is_secret_configured: boolean;
  deliveries_count: number;
  last_delivery_at?: string | null;
};

// GET /api/ai/status: the AI provider the backend started with, and whether it is in use.
export type AIStatus = {
  enabled: boolean;
  provider: string;
  model: string | null;
  endpoint: string | null;
  api_key_set: boolean | null;
  active: boolean;
  issue: string | null;
};

// POST /api/ai/test: one short request through the configured provider.
export type AITestResult = {
  ok: boolean;
  provider: string | null;
  model: string | null;
  latency_ms: number | null;
  reply: string | null;
  error: string | null;
};

// Metric usage: which metrics Grafana dashboards and alerts watch (backend/app/api/metric_usage.py).
export type MetricUsageStatus = 'blind_spot' | 'missing' | 'watched' | 'unwatched';

export type MetricUsageWatcher = {
  kind: 'dashboard' | 'alert_rule' | 'recording_rule';
  location: string;
  folder?: string | null;
  dashboard_uid?: string | null;
};

export type MetricUsageItem = {
  metric: string;
  status: MetricUsageStatus;
  connections: string[];
  usages: MetricUsageWatcher[];
  via_recording_rules: string[];
  problem_findings: number;
  latest_finding_id: number | null;
  analyzed: boolean;
  /** Active series, summed over connections; null when they couldn't be counted. */
  series: number | null;
  /** Active series per job label, per connection ("" for series without one). */
  jobs?: Record<string, Record<string, number>>;
  /** Declared type ("counter", "gauge", "histogram"...), or guessed from the name; null when unknown. */
  metric_type?: string | null;
  /** Made by a recording rule, not scraped. */
  recording_rule?: boolean;
  /** When a check first listed it; null when it was there before checks recorded that. */
  first_seen?: string | null;
  /** Why Drop isn't offered for it; null when it is. */
  drop_blocked?: string | null;
  /** What to check before dropping it. */
  drop_warnings?: string[];
};

/** A recording rule whose output no dashboard, alert or watched rule reads. */
export type MetricUsageUnreadRule = {
  name: string;
  groups: string[];
  connections: string[];
  reads: string[];
  /** Other recording rules that read it, all unread too. */
  feeds: string[];
  series: number | null;
  analyzed: boolean;
  /** What to check before removing it. */
  warnings?: string[];
};

/** Prometheus scrape config that drops the selected metrics: one block per Prometheus. */
export type MetricUsageDropConfig = {
  blocks: Array<{ connection: string; name: string; yaml: string }>;
  metrics: string[];
  series: number | null;
  skipped: Array<{ metric: string; reason: string }>;
  warnings: string[];
};

export type MetricUsageSnapshot = {
  id: string;
  trigger: string;
  status: 'completed' | 'failed';
  created_at: string;
  duration_ms: number | null;
  error: string | null;
  metrics_total: number;
  watched: number;
  blind_spots: number;
  unwatched: number;
  missing: number;
  watched_percent: number | null;
  series_total: number | null;
  series_unwatched: number | null;
  sources: {
    grafana?: { configured: boolean; dashboards_read?: number; dashboards_excluded?: string[]; alert_rules_read?: number };
    prometheus?: Array<{ id: string; name: string; metrics?: number; rule_groups: number }>;
    unresolved_queries?: Array<{ location: string; variables: string[] }>;
    warnings?: string[];
  };
};

export type MetricUsageResponse = {
  enabled: boolean;
  interval_hours: number;
  grafana_configured: boolean;
  snapshot: MetricUsageSnapshot | null;
  last_failure: MetricUsageSnapshot | null;
  items: MetricUsageItem[];
  items_total: number;
  /** Only when the operator set a cost per 1,000 series. */
  cost: MetricUsageCost | null;
  unread_rules?: MetricUsageUnreadRule[];
};

export type MetricUsageCost = {
  per_1k_series_month: number;
  currency: string;
  unwatched_monthly: number | null;
  total_monthly: number | null;
};

export type GrafanaStatus = {
  configured: boolean;
  url: string | null;
  reachable: boolean;
  version?: string | null;
  message: string;
};

export type SlackStatus = {
  enabled: boolean;
  delivered_last_24h: number;
  retrying: number;
  failed_last_24h: number;
  last_failure?: {
    title: string;
    service?: string | null;
    metric_name?: string | null;
    error?: string | null;
    attempts: number;
    status: 'pending' | 'failed' | string;
    created_at: string;
    next_retry_at?: string | null;
  } | null;
};
