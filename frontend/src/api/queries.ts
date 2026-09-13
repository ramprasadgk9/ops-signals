import { deleteJson, getJson, postForm, postJson, patchJson } from './client';
import type {
  AnalyzerConfigSuggestion,
  AnalyzerConfigSuggestionInput,
  AnalyzerRecommendation,
  AnalyzerRecommendationChatRequest,
  AnalyzerRecommendationChatResponse,
  AnalysisRun,
  BehaviorDefinition,
  BehaviorDefinitionDraft,
  BehaviorEvaluation,
  BehaviorFinding,
  BehaviorPatternSuggestion,
  Capability,
  FactDescriptor,
  SaveDraftResult,
  CsvRunResult,
  Finding,
  MetricAnalyzerRecommendation,
  MetricSample,
  ExperimentComparison,
  ExperimentResult,
  RouterResponse,
  AssistantChatRequest,
  AssistantChatResponse,
  MemoryChatRequest,
  MemoryChatResponse,
  CsvValidationResult,
  DirectPrometheusAnalysisRequest,
  DirectPrometheusAnalysisResponse,
  OperationalCase,
  PrometheusConnectionsResponse,
  PrometheusConnectionTestResponse,
  PrometheusLabelValuesResponse,
  PrometheusPreviewResponse,
  Question,
  QuestionAnswer,
  Signal,
  TimeseriesPoint,
  OverviewSummaryResponse,
  MemoryStatsResponse,
  BenchmarkReportResponse,
  BenchmarkRunRequestPayload,
  BenchmarkScenarioDescriptor,
  ValidationResult,
} from '../types';
import type { AutonomousPolicyRun } from '../autonomous/dashboardModel';
import type { AutonomousPreviewRequest, AutonomousPreviewResponse, AutonomousRunResponse } from '../grafana/contracts';

export type FindingsWindow = '1h' | '6h' | '24h' | '7d';

export type AutonomousQuestionAnswer = {
  headline: string;
  answer: string;
  ai_synthesis_used?: boolean;
  priority: string;
  confidence: number;
  key_points: string[];
  evidence: Record<string, unknown>;
};

export const api = {
  health: () => getJson<{ status: string }>('/api/health'),
  overviewSummary: (window: '24h' | '7d' = '24h') => getJson<OverviewSummaryResponse>(`/api/overview/summary?window=${window}`),
  services: () => getJson<string[]>('/api/services'),
  metrics: (service: string) => getJson<string[]>(`/api/services/${service}/metrics`),
  analysisRuns: () => getJson<AnalysisRun[]>('/api/analysis-runs'),
  capabilities: () => getJson<Capability[]>('/api/capabilities'),
  behaviorDefinitions: () => getJson<BehaviorDefinition[]>('/api/behavior-definitions'),
  behaviorFindings: (analysisRunId?: string, service?: string) => {
    const params = new URLSearchParams();
    if (analysisRunId) params.append('analysis_run_id', analysisRunId);
    if (service) params.append('service', service);
    const queryString = params.toString();
    return getJson<BehaviorFinding[]>(`/api/behavior-evaluations${queryString ? `?${queryString}` : ''}`);
  },
  behaviorFacts: () => getJson<FactDescriptor[]>('/api/behavior-definitions/facts'),
  behaviorAvailableMetrics: () => getJson<string[]>('/api/behavior-definitions/available-metrics'),
  validateBehaviorDefinition: (draft: BehaviorDefinitionDraft) =>
    postJson<BehaviorDefinitionDraft, ValidationResult>('/api/behavior-definitions/validate', draft),
  dryRunBehaviorDefinition: (draft: BehaviorDefinitionDraft, analysisRunId: string, service?: string) =>
    postJson<{ definition: BehaviorDefinitionDraft; analysis_run_id: string; service?: string }, BehaviorEvaluation>(
      '/api/behavior-definitions/dry-run',
      { definition: draft, analysis_run_id: analysisRunId, service }
    ),
  saveBehaviorDefinitionToPack: (draft: BehaviorDefinitionDraft, packFile: string) =>
    postJson<{ definition: BehaviorDefinitionDraft; pack_file: string }, SaveDraftResult>(
      '/api/behavior-definitions/save-to-pack',
      { definition: draft, pack_file: packFile }
    ),
  mineBehaviorSuggestions: () => postJson<Record<string, never>, BehaviorPatternSuggestion[]>('/api/behavior-definitions/suggestions/mine', {}),
  behaviorSuggestions: (status: string = 'pending') =>
    getJson<BehaviorPatternSuggestion[]>(`/api/behavior-definitions/suggestions?status=${encodeURIComponent(status)}`),
  dismissBehaviorSuggestion: (id: number) =>
    postJson<Record<string, never>, BehaviorPatternSuggestion>(`/api/behavior-definitions/suggestions/${id}/dismiss`, {}),
  promoteBehaviorSuggestion: (id: number, packFile?: string) =>
    postJson<{ pack_file?: string }, BehaviorPatternSuggestion>(`/api/behavior-definitions/suggestions/${id}/promote`, {
      pack_file: packFile ?? 'suggested_patterns.yml',
    }),
  behaviorEvaluations: (analysisRunId?: string, service?: string) =>
    getJson<BehaviorEvaluation[]>(
      analysisRunId
        ? `/api/behavior-evaluations/evaluate?analysis_run_id=${encodeURIComponent(analysisRunId)}${service ? `&service=${encodeURIComponent(service)}` : ''}`
        : '/api/behavior-evaluations/evaluate'
    ),
  questions: () => getJson<Question[]>('/api/questions'),
  availableQuestions: (service: string, metric: string, runId: string) =>
    getJson<Question[]>(`/api/questions/available?service=${encodeURIComponent(service)}&metric_name=${encodeURIComponent(metric)}&analysis_run_id=${encodeURIComponent(runId)}`),
  questionAnswer: (question_id: string, service: string, metric_name: string, analysis_run_id: string) =>
    postJson<{ question_id: string; service: string; metric_name: string; analysis_run_id: string }, QuestionAnswer>('/api/questions/answer', {
      question_id,
      service,
      metric_name,
      analysis_run_id,
    }),
  signals: (service: string, metric: string, runId: string) =>
    getJson<Signal[]>(`/api/signals?service=${encodeURIComponent(service)}&metric_name=${encodeURIComponent(metric)}&analysis_run_id=${encodeURIComponent(runId)}`),
  signalDetail: (signalId: string) => getJson<Signal>(`/api/signals/${signalId}`),
  signalsByRunIds: async (analysisRunIds: string[]): Promise<Signal[]> => {
    const uniqueRunIds = Array.from(new Set(analysisRunIds));
    const results = await Promise.all(
      uniqueRunIds.map((runId) => getJson<Signal[]>(`/api/signals?analysis_run_id=${encodeURIComponent(runId)}`))
    );
    return results.flat();
  },
  findings: (service?: string, metric?: string, runId?: string, window?: FindingsWindow) => {
    const params = new URLSearchParams();
    if (service) params.append('service', service);
    if (metric) params.append('metric_name', metric);
    if (runId) params.append('analysis_run_id', runId);
    if (window) params.append('window', window);
    const queryString = params.toString();
    return getJson<Finding[]>(`/api/findings${queryString ? `?${queryString}` : ''}`);
  },
  findingsSearch: (params: { window?: FindingsWindow; q?: string; service?: string; metric_name?: string; limit?: number }) => {
    const queryParams = new URLSearchParams();
    queryParams.append('window', params.window ?? '24h');
    queryParams.append('limit', String(params.limit ?? 10));
    if (params.q) queryParams.append('q', params.q);
    if (params.service) queryParams.append('service', params.service);
    if (params.metric_name) queryParams.append('metric_name', params.metric_name);
    return getJson<Finding[]>(`/api/findings/search?${queryParams.toString()}`);
  },
  getFinding: (findingId: number) => getJson<Finding>(`/api/findings/${findingId}`),
  cases: (limit?: number) => getJson<OperationalCase[]>(`/api/cases${limit ? `?limit=${limit}` : ''}`),
  autonomousPolicyRuns: (limit = 25) => getJson<AutonomousPolicyRun[]>(`/api/autonomous/policy-runs?limit=${limit}`),
  autonomousPolicyRunJobs: (policyRunId: string) => getJson<Record<string, unknown>[]>(`/api/autonomous/policy-runs/${encodeURIComponent(policyRunId)}/jobs`),
  autonomousScopeOptions: (labels: { service_label?: string; namespace_label?: string; environment_label?: string } = {}) => {
    const params = new URLSearchParams();
    params.append('service_label', labels.service_label ?? 'service');
    params.append('namespace_label', labels.namespace_label ?? 'namespace');
    params.append('environment_label', labels.environment_label ?? 'env');
    return getJson<{ services: string[]; namespaces: string[]; environments: string[] }>(`/api/autonomous/scope-options?${params.toString()}`);
  },
  autonomousPreview: (payload: AutonomousPreviewRequest) =>
    postJson<AutonomousPreviewRequest, AutonomousPreviewResponse>('/api/autonomous/preview', payload),
  autonomousRunOnce: (payload: AutonomousPreviewRequest) =>
    postJson<AutonomousPreviewRequest & { dry_run: boolean }, AutonomousRunResponse>('/api/autonomous/run-once', { ...payload, dry_run: false }),
  autonomousQuestionAnswer: (payload: { question: string; policy_run_id?: string | null; window?: FindingsWindow; service?: string; metric_name?: string }) =>
    postJson<typeof payload, AutonomousQuestionAnswer>('/api/autonomous/questions/answer', payload),
  createCase: (findingId: number) =>
    postJson<{}, { case_id: number; finding_id: number; case_status: string; memory_status: string }>(`/api/cases/findings/${findingId}/create`, {}),
  getCase: (caseId: number) => getJson<OperationalCase>(`/api/cases/${caseId}`),
  updateInvestigation: (caseId: number, payload: { investigation_status: string; investigation_note?: string }) =>
    patchJson<typeof payload, OperationalCase>(`/api/cases/${caseId}/investigation`, payload),
  updateRCA: (caseId: number, payload: { root_cause_status: string; root_cause_summary?: string; root_cause_confidence?: number; root_cause_verified: boolean }) =>
    patchJson<typeof payload, OperationalCase>(`/api/cases/${caseId}/rca`, payload),
  updateResolution: (caseId: number, payload: { outcome_status: string; outcome_summary?: string; corrective_action?: string }) =>
    patchJson<typeof payload, OperationalCase>(`/api/cases/${caseId}/resolution`, payload),
  
  // Memory API calls
  indexCaseMemory: (caseId: number) =>
    postJson<{}, { case_id: number; memory_status: string; indexed_at?: string }>(
      `/api/cases/${caseId}/memory/index`,
      {}
    ),
  getMemoryStatus: (caseId: number) =>
    getJson<{ case_id: number; memory_status: string; memory_indexed_at?: string; memory_error?: string }>(
      `/api/cases/${caseId}/memory/status`
    ),
  getSimilarCases: (caseId: number, topK?: number, minimumScore?: number) =>
    getJson<any>(
      `/api/cases/${caseId}/similar?top_k=${topK ?? 5}&minimum_score=${minimumScore ?? 0.7}`
    ),
  deleteMemory: (caseId: number) =>
    getJson<{ status: string; case_id: number; memory_status: string }>(
      `/api/cases/${caseId}/memory`
    ),
  memoryHealth: () =>
    getJson<{ enabled: boolean; provider: string; status: string; collection: string }>(
      '/api/memory/health'
    ),
  memoryStats: () => getJson<MemoryStatsResponse>('/api/memory/stats'),
  metricAnalyzerSamples: () => getJson<MetricSample[]>('/api/metric-analyzer-recommendations/metrics'),
  metricAnalyzerEvaluate: (service: string, metricName: string, analysisRunId?: string | null) =>
    postJson<
      { service: string; metric_name: string; analysis_run_id?: string | null },
      MetricAnalyzerRecommendation
    >('/api/metric-analyzer-recommendations/evaluate', {
      service,
      metric_name: metricName,
      analysis_run_id: analysisRunId ?? null,
    }),
  metricAnalyzerChat: (payload: AnalyzerRecommendationChatRequest) =>
    postJson<AnalyzerRecommendationChatRequest, AnalyzerRecommendationChatResponse>('/api/metric-analyzer-recommendations/chat', payload),
  assistantChat: (payload: AssistantChatRequest) =>
    postJson<AssistantChatRequest, AssistantChatResponse>('/api/assistant/chat', payload),
  memoryChat: (payload: MemoryChatRequest) =>
    postJson<MemoryChatRequest, MemoryChatResponse>('/api/memory/chat', payload),
  experiments: () => getJson<ExperimentResult[]>('/api/experiments'),
  experiment: (experimentId: string) => getJson<ExperimentResult>(`/api/experiments/${experimentId}`),
  experimentCompare: (experimentIds: string[]) => {
    const params = new URLSearchParams();
    experimentIds.forEach((id) => params.append('experiment_ids', id));
    return getJson<ExperimentComparison>(`/api/experiments/compare?${params.toString()}`);
  },
  analyzerRouterRoute: (payload: FormData) => postForm<RouterResponse>('/api/experiment-analyzer-router/route', payload),
  analyzerLabConfigSuggestions: (analyzerId?: string) =>
    getJson<AnalyzerConfigSuggestion[]>(
      `/api/analyzer-labs/config-suggestions${analyzerId ? `?analyzer_id=${encodeURIComponent(analyzerId)}` : ''}`
    ),
  saveAnalyzerLabConfigSuggestion: (payload: AnalyzerConfigSuggestionInput) =>
    postJson<AnalyzerConfigSuggestionInput, AnalyzerConfigSuggestion>('/api/analyzer-labs/config-suggestions', payload),
  deleteAnalyzerLabConfigSuggestion: (suggestionId: number) =>
    deleteJson<{ deleted: number }>(`/api/analyzer-labs/config-suggestions/${suggestionId}`),
  clearAnalyzerLabConfigSuggestions: (analyzerId?: string) =>
    deleteJson<{ deleted: number }>(
      `/api/analyzer-labs/config-suggestions${analyzerId ? `?analyzer_id=${encodeURIComponent(analyzerId)}` : ''}`
    ),
  
  timeseries: (service: string, metric: string, runId: string) =>
    getJson<TimeseriesPoint[]>(`/api/timeseries?service=${encodeURIComponent(service)}&metric_name=${encodeURIComponent(metric)}&analysis_run_id=${encodeURIComponent(runId)}`),
  runCsvUpload: (payload: FormData) => postForm<CsvRunResult>('/api/ingestion/csv-run', payload),
  runCsvValidation: (payload: FormData) => postForm<CsvValidationResult>('/api/ingestion/csv-validate', payload),
  prometheusConnections: () => getJson<PrometheusConnectionsResponse>('/api/prometheus/connections'),
  prometheusLabelValues: (label: string, connectionId = 'default') =>
    getJson<PrometheusLabelValuesResponse>(
      `/api/prometheus/label-values?label=${encodeURIComponent(label)}&connection_id=${encodeURIComponent(connectionId)}`
    ),
  testPrometheusConnection: (connectionId: string) =>
    postJson<{ connection_id: string }, PrometheusConnectionTestResponse>('/api/prometheus/test-connection', { connection_id: connectionId }),
  previewPrometheus: (payload: { connection_id: string; query: string; start: string; end: string; step: string }) =>
    postJson<typeof payload, PrometheusPreviewResponse>('/api/prometheus/preview', payload),
  runPrometheusAnalysis: (payload: DirectPrometheusAnalysisRequest) =>
    postJson<DirectPrometheusAnalysisRequest, DirectPrometheusAnalysisResponse>('/api/analysis/prometheus', payload),
  benchmarkScenarios: () => getJson<BenchmarkScenarioDescriptor[]>('/api/benchmark/scenarios'),
  benchmarkReport: () => getJson<BenchmarkReportResponse>('/api/benchmark/report'),
  runBenchmark: (payload: BenchmarkRunRequestPayload) =>
    postJson<BenchmarkRunRequestPayload, BenchmarkReportResponse>('/api/benchmark/run', payload),
};
