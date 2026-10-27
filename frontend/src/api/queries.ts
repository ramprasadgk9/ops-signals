import { deleteJson, getHealth, getJson, postForm, postJson, patchJson } from './client';
import type { SetupCheckResult } from '../utils/setupCheck';
import type { Me } from '../hooks/useWebPermissions';

/** Setup check's Test sign-in (GET /api/auth/test). */
export type SignInTest = { reachable: boolean; issuer: string | null; redirect_uri: string; detail: string; test_provider: boolean };
import type {
  AnalyzerConfigSuggestion,
  AnalyzerConfigSuggestionInput,
  AnalyzerRecommendation,
  AnalyzerRecommendationChatRequest,
  AnalyzerRecommendationChatResponse,
  AnalysisRun,
  BehaviorDefinition,
  CatalogPattern,
  HistoryPreview,
  BehaviorDefinitionDraft,
  BehaviorEvaluation,
  BehaviorFinding,
  BehaviorPatternSuggestion,
  Capability,
  FactDescriptor,
  SaveDraftResult,
  CsvRunResult,
  Finding,
  FindingVerdict,
  MetricAnalyzerRecommendation,
  MetricSample,
  RouterResponse,
  AssistantChatRequest,
  AssistantChatResponse,
  MemoryChatRequest,
  MemoryChatResponse,
  AlertContextResponse,
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
  SlackStatus,
  TimeseriesPoint,
  OverviewSummaryResponse,
  MemoryStatsResponse,
  RecurringProblemsResponse,
  CoverageReport,
  RunbookDraft,
  SameFixResponse,
  SuggestedFixesResponse,
  AlertItem,
  AlertListParams,
  AlertReceipt,
  CaseTicketLink,
  CaseTicketOperation,
  CaseTicketEvent,
  CaseNotePromoteResult,
  CommentTriageResult,
  AmbiguousResolutionPayload,
  TicketingStatus,
  WebhookInfoView,
  IngestionStatus,
  OtlpStatus,
  ValidationResult,
  KnowledgeReindexResult,
  KnowledgeStatus,
  StarterQuestions,
  AssistantFeedback,
  AssistantFeedbackCreate,
  AssistantFeedbackUpdate,
  FlaggedQuestion,
  DocsCoverage,
  DraftQuestion,
  DocQuestionEvaluation,
  NewDocTest,
  SaveDocTestsResult,
  CaseImportBatch,
  AIStatus,
  FindingAIWording,
  CaseRcaDraft,
  CaseResolutionDraft,
  CaseTimeline,
  CaseWriteupDraft,
  AITestResult,
  CaseImportPreview,
  CaseImportProfiles,
  CaseImportResult,
  SeenBeforeResponse,
  SimilarCasesResponse,
  MetricUsageResponse,
  MetricUsageSnapshot,
  MetricUsageItem,
  MetricUsageDropConfig,
  MetricUsageStatus,
  GrafanaStatus,
} from '../types';
import type { AutonomousPolicyRun } from '../autonomous/dashboardModel';
import type { AutonomousPolicy, AutonomousPolicySaveRequest, AutonomousPreviewRequest, AutonomousPreviewResponse, AutonomousRunResponse } from '../grafana/contracts';

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

const SIGNAL_RUNS_PER_REQUEST = 100;

export const api = {
  health: () => getHealth(),
  slackStatus: () => getJson<SlackStatus>('/api/notifications/slack'),
  otlpStatus: () => getJson<OtlpStatus>('/api/otlp/status'),
  ingestionStatus: () => getJson<IngestionStatus>('/api/ingestion/status'),
  setupCheck: () => getJson<SetupCheckResult>('/api/setup/check'),
  setupSummary: () => getJson<SetupCheckResult>('/api/setup/summary'),
  me: () => getJson<Me>('/api/me'),
  signOut: () => postJson<Record<string, never>, { redirect: string }>('/api/auth/logout', {}),
  testSignIn: () => getJson<SignInTest>('/api/auth/test'),
  sendTestAlert: () => postJson<Record<string, never>, AlertReceipt>('/api/integrations/alertmanager/test', {}),
  alerts: (params: AlertListParams = {}) => {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') search.set(key, String(value));
    });
    const query = search.toString();
    return getJson<AlertItem[]>(`/api/alerts${query ? `?${query}` : ''}`);
  },
  metricUsage: (statuses: MetricUsageStatus[] = [], limit = 200) => {
    const search = new URLSearchParams({ limit: String(limit) });
    statuses.forEach((status) => search.append('status', status));
    return getJson<MetricUsageResponse>(`/api/metric-usage?${search.toString()}`);
  },
  metricUsageLookup: (names: string[]) => {
    const search = new URLSearchParams();
    names.forEach((name) => search.append('name', name));
    return getJson<Record<string, MetricUsageItem>>(`/api/metric-usage/metrics?${search.toString()}`);
  },
  metricUsageHistory: (limit = 28) => getJson<MetricUsageSnapshot[]>(`/api/metric-usage/history?limit=${limit}`),
  metricUsageDropConfig: (metrics: string[]) => postJson<{ metrics: string[] }, MetricUsageDropConfig>('/api/metric-usage/drop-config', { metrics }),
  runMetricUsageCheck: () => postJson<Record<string, never>, MetricUsageSnapshot>('/api/metric-usage/run', {}),
  grafanaStatus: () => getJson<GrafanaStatus>('/api/metric-usage/grafana/status'),
  overviewSummary: (window: '6h' | '24h' | '7d' = '24h') => getJson<OverviewSummaryResponse>(`/api/overview/summary?window=${window}`),
  services: () => getJson<string[]>('/api/services'),
  metrics: (service: string) => getJson<string[]>(`/api/services/${service}/metrics`),
  analysisRuns: () => getJson<AnalysisRun[]>('/api/analysis-runs'),
  analysisRun: (runId: string) => getJson<AnalysisRun>(`/api/analysis-runs/${runId}`),
  capabilities: () => getJson<Capability[]>('/api/capabilities'),
  behaviorDefinitions: () => getJson<BehaviorDefinition[]>('/api/behavior-definitions'),
  behaviorCatalog: () => getJson<CatalogPattern[]>('/api/behavior-definitions/catalog'),
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
  /** With metrics: only the services where one of them changed recently, most of them first. */
  behaviorHistoryServices: (metrics: string[] = []) =>
    getJson<string[]>(`/api/behavior-definitions/history-services${metrics.length ? `?${metrics.map((metric) => `metric=${encodeURIComponent(metric)}`).join('&')}` : ''}`),
  behaviorHistoryPreview: (draft: BehaviorDefinitionDraft, service: string, hours: number) =>
    postJson<{ definition: BehaviorDefinitionDraft; service: string; hours: number }, HistoryPreview>(
      '/api/behavior-definitions/history-preview',
      { definition: draft, service, hours }
    ),
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
    // Many runs per request (a 7-day findings list can span thousands of runs), in chunks that keep
    // the URL short.
    const uniqueRunIds = Array.from(new Set(analysisRunIds));
    const chunks: string[][] = [];
    for (let index = 0; index < uniqueRunIds.length; index += SIGNAL_RUNS_PER_REQUEST) {
      chunks.push(uniqueRunIds.slice(index, index + SIGNAL_RUNS_PER_REQUEST));
    }
    const results = await Promise.all(
      chunks.map((chunk) => {
        const params = new URLSearchParams();
        chunk.forEach((runId) => params.append('analysis_run_id', runId));
        return getJson<Signal[]>(`/api/signals?${params.toString()}`);
      })
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
  findingFeedback: (findingId: number, verdict: FindingVerdict) =>
    postJson<{ verdict: FindingVerdict }, Finding>(`/api/findings/${findingId}/feedback`, { verdict }),
  cases: (limit?: number) => getJson<OperationalCase[]>(`/api/cases${limit ? `?limit=${limit}` : ''}`),
  autonomousPolicyRuns: (limit = 25) => getJson<AutonomousPolicyRun[]>(`/api/autonomous/policy-runs?limit=${limit}`),
  autonomousPolicyRunJobs: (policyRunId: string) => getJson<Record<string, unknown>[]>(`/api/autonomous/policy-runs/${encodeURIComponent(policyRunId)}/jobs`),
  autonomousScopeOptions: (labels: { service_label?: string; namespace_label?: string; environment_label?: string; window?: string; connection_id?: string } = {}) => {
    const params = new URLSearchParams();
    if (labels.connection_id) params.append('connection_id', labels.connection_id);
    params.append('service_label', labels.service_label ?? 'service');
    params.append('namespace_label', labels.namespace_label ?? 'namespace');
    params.append('environment_label', labels.environment_label ?? 'env');
    params.append('window', labels.window ?? '24h');
    return getJson<{ services: string[]; namespaces: string[]; environments: string[]; clusters?: string[]; cluster_label?: string | null }>(
      `/api/autonomous/scope-options?${params.toString()}`
    );
  },
  autonomousPreview: (payload: AutonomousPreviewRequest) =>
    postJson<AutonomousPreviewRequest, AutonomousPreviewResponse>('/api/autonomous/preview', payload),
  autonomousRunOnce: (payload: AutonomousPreviewRequest) =>
    postJson<AutonomousPreviewRequest & { dry_run: boolean }, AutonomousRunResponse>('/api/autonomous/run-once', { ...payload, dry_run: false }),
  autonomousQuestionAnswer: (payload: { question: string; policy_run_id?: string | null; window?: FindingsWindow; service?: string; metric_name?: string }) =>
    postJson<typeof payload, AutonomousQuestionAnswer>('/api/autonomous/questions/answer', payload),
  autonomousListPolicies: (limit = 50) => getJson<AutonomousPolicy[]>(`/api/autonomous/policies?limit=${limit}`),
  autonomousSavePolicy: (payload: AutonomousPolicySaveRequest) =>
    postJson<AutonomousPolicySaveRequest, AutonomousPolicy>('/api/autonomous/policies', payload),
  autonomousUpdatePolicy: (policyId: string, payload: AutonomousPolicySaveRequest) =>
    patchJson<AutonomousPolicySaveRequest, AutonomousPolicy>(`/api/autonomous/policies/${encodeURIComponent(policyId)}`, payload),
  autonomousSetPolicyStatus: (policyId: string, enabled: boolean) =>
    patchJson<{ enabled: boolean }, AutonomousPolicy>(`/api/autonomous/policies/${encodeURIComponent(policyId)}/status`, { enabled }),
  autonomousDeletePolicy: (policyId: string) =>
    deleteJson<{ deleted: boolean; id: string }>(`/api/autonomous/policies/${encodeURIComponent(policyId)}`),
  createCase: (findingId: number) =>
    postJson<{}, { case_id: number; finding_id: number; case_status: string; memory_status: string }>(`/api/cases/findings/${findingId}/create`, {}),
  createCaseFromBehavior: (behaviorFindingId: number) =>
    postJson<{}, { case_id: number; behavior_finding_id: number; case_status: string; memory_status: string }>(
      `/api/cases/behaviors/${behaviorFindingId}/create`,
      {}
    ),
  getCase: (caseId: number) => getJson<OperationalCase>(`/api/cases/${caseId}`),
  updateInvestigation: (caseId: number, payload: { investigation_status: string; investigation_note?: string }) =>
    patchJson<typeof payload, OperationalCase>(`/api/cases/${caseId}/investigation`, payload),
  updateRCA: (caseId: number, payload: { root_cause_status: string; root_cause_summary?: string; root_cause_confidence?: number; root_cause_verified: boolean }) =>
    patchJson<typeof payload, OperationalCase>(`/api/cases/${caseId}/rca`, payload),
  updateResolution: (
    caseId: number,
    payload: { outcome_status: string; outcome_summary?: string; corrective_action?: string; learning_outcome_status?: string }
  ) => patchJson<typeof payload, OperationalCase>(`/api/cases/${caseId}/resolution`, payload),
  suggestRca: (caseId: number) => postJson<Record<string, never>, CaseRcaDraft>(`/api/cases/${caseId}/rca/suggest`, {}),
  caseTimeline: (caseId: number) => getJson<CaseTimeline>(`/api/cases/${caseId}/timeline`),
  updateWriteup: (caseId: number, writeup: string) => patchJson<{ writeup: string }, OperationalCase>(`/api/cases/${caseId}/writeup`, { writeup }),
  suggestWriteup: (caseId: number) => postJson<Record<string, never>, CaseWriteupDraft>(`/api/cases/${caseId}/writeup/suggest`, {}),
  suggestResolution: (caseId: number) => postJson<Record<string, never>, CaseResolutionDraft>(`/api/cases/${caseId}/resolution/suggest`, {}),
  
  // Ticketing API calls
  getCaseTicket: (caseId: number) => getJson<CaseTicketLink | null>(`/api/cases/${caseId}/ticket`),
  createCaseTicket: (caseId: number, provider?: string) =>
    postJson<{ provider?: string }, CaseTicketOperation>(`/api/cases/${caseId}/ticket/create`, { provider }),
  syncCaseTicket: (caseId: number, provider?: string) =>
    postJson<{ provider?: string }, CaseTicketOperation>(`/api/cases/${caseId}/ticket/sync`, { provider }),
  retryCaseTicketOperation: (caseId: number, operationId: string) =>
    postJson<{ operation_id: string }, CaseTicketOperation>(`/api/cases/${caseId}/ticket/retry`, { operation_id: operationId }),
  linkExistingTicket: (caseId: number, displayKey: string, provider?: string) =>
    postJson<{ display_key: string; provider?: string }, CaseTicketLink>(`/api/cases/${caseId}/ticket/link`, { display_key: displayKey, provider }),
  resolveAmbiguousTicket: (caseId: number, payload: AmbiguousResolutionPayload) =>
    postJson<AmbiguousResolutionPayload, any>(`/api/cases/${caseId}/ticket/resolve-ambiguity`, payload),
  getCaseTicketEvents: (caseId: number) => getJson<CaseTicketEvent[]>(`/api/cases/${caseId}/ticket/events`),
  promoteTicketCommentToNote: (caseId: number, eventId: number) =>
    postJson<Record<string, never>, CaseNotePromoteResult>(
      `/api/cases/${caseId}/ticket/events/${eventId}/promote-to-note`,
      {}
    ),
  triageCaseTicketComments: (caseId: number) =>
    postJson<Record<string, never>, CommentTriageResult>(
      `/api/cases/${caseId}/ticket/triage-comments`,
      {}
    ),
  getCaseTicketOperation: (caseId: number, operationId: string) =>
    getJson<CaseTicketOperation>(`/api/cases/${caseId}/ticket/operations/${encodeURIComponent(operationId)}`),
  resolveCaseTicket: (caseId: number, provider?: string) =>
    postJson<{ provider?: string }, CaseTicketOperation | null>(`/api/cases/${caseId}/ticket/resolve`, { provider }),
  ticketingStatus: () => getJson<TicketingStatus>('/api/integrations/ticketing/status'),
  getTicketingWebhookInfo: (provider: string = 'jira') =>
    getJson<WebhookInfoView>(`/api/integrations/ticketing/${encodeURIComponent(provider)}/webhook-info`),

  
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
  findingSeenBefore: (findingId: number) => getJson<SeenBeforeResponse>(`/api/findings/${findingId}/seen-before`),
  findingsSeenBefore: (findingIds: number[]) =>
    postJson<{ finding_ids: number[] }, SeenBeforeResponse[]>('/api/findings/seen-before', { finding_ids: findingIds }),
  getSimilarCases: (caseId: number, topK?: number, minimumScore?: number) =>
    getJson<SimilarCasesResponse>(
      `/api/cases/${caseId}/similar?top_k=${topK ?? 5}&minimum_score=${minimumScore ?? 0.7}`
    ),
  deleteMemory: (caseId: number) =>
    getJson<{ status: string; case_id: number; memory_status: string }>(
      `/api/cases/${caseId}/memory`
    ),
  memoryHealth: () =>
    getJson<{ enabled: boolean; provider: string; status: string; collection: string; detail?: string | null }>(
      '/api/memory/health'
    ),
  memoryStats: () => getJson<MemoryStatsResponse>('/api/memory/stats'),
  // name=false skips the LLM naming the groups, for callers that only need which group a case is in.
  recurringProblems: (days = 90, minOccurrences = 3, groupBy: 'symptom' | 'cause' = 'symptom', name = true) =>
    getJson<RecurringProblemsResponse>(`/api/memory/recurring-problems?days=${days}&min_occurrences=${minOccurrences}&group_by=${groupBy}${name ? '' : '&name=false'}`),
  monitoringCoverage: (days = 365) => getJson<CoverageReport>(`/api/memory/coverage?days=${days}`),
  suggestedFixes: (findingId: number) => getJson<SuggestedFixesResponse>(`/api/findings/${findingId}/suggested-fixes`),
  findingAiWording: (findingId: number) => getJson<FindingAIWording>(`/api/findings/${findingId}/ai-wording`),
  runbookDraft: (findingId: number) =>
    postJson<Record<string, never>, RunbookDraft>(`/api/findings/${findingId}/suggested-fixes/runbook-draft`, {}),
  sameFix: (caseId: number) => getJson<SameFixResponse>(`/api/cases/${caseId}/same-fix`),
  caseImportProfiles: () => getJson<CaseImportProfiles>('/api/case-imports/profiles'),
  caseImportTemplateUrl: (name: string) => `${import.meta.env.VITE_API_BASE ?? ''}/api/case-imports/templates/${encodeURIComponent(name)}`,
  previewCaseImport: (payload: FormData) => postForm<CaseImportPreview>('/api/case-imports/preview', payload),
  runCaseImport: (payload: FormData) => postForm<CaseImportResult>('/api/case-imports', payload),
  caseImports: () => getJson<CaseImportBatch[]>('/api/case-imports'),
  aiStatus: () => getJson<AIStatus>('/api/ai/status'),
  testAiConnection: () => postJson<Record<string, never>, AITestResult>('/api/ai/test', {}),
  undoCaseImport: (batchId: string) => deleteJson<{ batch_id: string; deleted_cases: number }>(`/api/case-imports/${batchId}`),
  alertContext: (metricName: string, service?: string, message?: string) => {
    const params = new URLSearchParams({ metric_name: metricName });
    if (service) params.append('service', service);
    if (message) params.append('message', message);
    return getJson<AlertContextResponse>(`/api/alert-context?${params.toString()}`);
  },
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
  reindexKnowledge: () => postJson<Record<string, never>, KnowledgeReindexResult>('/api/assistant/knowledge/bootstrap', {}),
  knowledgeStatus: () => getJson<KnowledgeStatus>('/api/assistant/knowledge/status'),
  starterQuestions: () => getJson<StarterQuestions>('/api/assistant/starter-questions'),
  sendAssistantFeedback: (payload: AssistantFeedbackCreate) => postJson<AssistantFeedbackCreate, AssistantFeedback>('/api/assistant/feedback', payload),
  updateAssistantFeedback: (id: number, payload: AssistantFeedbackUpdate) =>
    patchJson<AssistantFeedbackUpdate, AssistantFeedback>(`/api/assistant/feedback/${id}`, payload),
  flaggedQuestions: () => getJson<FlaggedQuestion[]>('/api/assistant/feedback/flagged'),
  docsCoverage: () => getJson<DocsCoverage>('/api/assistant/docs-check/coverage'),
  draftDocQuestions: (sourcePath: string) =>
    postJson<{ source_path: string }, DraftQuestion[]>('/api/assistant/docs-check/draft', { source_path: sourcePath }),
  evaluateDocQuestion: (payload: { question: string; source_path: string; section?: string | null }) =>
    postJson<typeof payload, DocQuestionEvaluation>('/api/assistant/docs-check/evaluate', payload),
  saveDocTests: (tests: NewDocTest[], dryRun: boolean) =>
    postJson<{ tests: NewDocTest[]; dry_run: boolean }, SaveDocTestsResult>('/api/assistant/docs-check/tests', { tests, dry_run: dryRun }),
  memoryChat: (payload: MemoryChatRequest) =>
    postJson<MemoryChatRequest, MemoryChatResponse>('/api/memory/chat', payload),
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
  
  timeseries: (service: string, metric: string, runId: string, cluster?: string | null) =>
    getJson<TimeseriesPoint[]>(
      `/api/timeseries?service=${encodeURIComponent(service)}&metric_name=${encodeURIComponent(metric)}&analysis_run_id=${encodeURIComponent(runId)}${cluster ? `&cluster=${encodeURIComponent(cluster)}` : ''}`
    ),
  runCsvUpload: (payload: FormData) => postForm<CsvRunResult>('/api/ingestion/csv-run', payload),
  runCsvValidation: (payload: FormData) => postForm<CsvValidationResult>('/api/ingestion/csv-validate', payload),
  prometheusConnections: () => getJson<PrometheusConnectionsResponse>('/api/prometheus/connections'),
  prometheusLabelValues: (label: string, connectionId = 'default', filter?: { match?: string[]; start?: string; end?: string }) => {
    const params = new URLSearchParams({ label, connection_id: connectionId });
    // Only values on series these selectors match, within the time range.
    (filter?.match ?? []).forEach((selector) => params.append('match', selector));
    if (filter?.start) params.append('start', filter.start);
    if (filter?.end) params.append('end', filter.end);
    return getJson<PrometheusLabelValuesResponse>(`/api/prometheus/label-values?${params.toString()}`);
  },
  testPrometheusConnection: (connectionId: string) =>
    postJson<{ connection_id: string }, PrometheusConnectionTestResponse>('/api/prometheus/test-connection', { connection_id: connectionId }),
  previewPrometheus: (payload: { connection_id: string; query: string; start: string; end: string; step: string }) =>
    postJson<typeof payload, PrometheusPreviewResponse>('/api/prometheus/preview', payload),
  runPrometheusAnalysis: (payload: DirectPrometheusAnalysisRequest) =>
    postJson<DirectPrometheusAnalysisRequest, DirectPrometheusAnalysisResponse>('/api/analysis/prometheus', payload),
};
