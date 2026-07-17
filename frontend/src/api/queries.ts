import { getJson, postForm, postJson, patchJson } from './client';
import type {
  AnalyzerRecommendation,
  AnalyzerRecommendationChatRequest,
  AnalyzerRecommendationChatResponse,
  AnalysisRun,
  BehaviorDefinition,
  BehaviorEvaluation,
  BehaviorFinding,
  Capability,
  CsvRunResult,
  Finding,
  MetricAnalyzerRecommendation,
  MetricSample,
  OperationalCase,
  Question,
  QuestionAnswer,
  Signal,
  TimeseriesPoint,
} from '../types';

export const api = {
  health: () => getJson<{ status: string }>('/api/health'),
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
  findings: (service?: string, metric?: string, runId?: string) => {
    const params = new URLSearchParams();
    if (service) params.append('service', service);
    if (metric) params.append('metric_name', metric);
    if (runId) params.append('analysis_run_id', runId);
    const queryString = params.toString();
    return getJson<Finding[]>(`/api/findings${queryString ? `?${queryString}` : ''}`);
  },
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
  
  timeseries: (service: string, metric: string, runId: string) =>
    getJson<TimeseriesPoint[]>(`/api/timeseries?service=${encodeURIComponent(service)}&metric_name=${encodeURIComponent(metric)}&analysis_run_id=${encodeURIComponent(runId)}`),
  runCsvUpload: (payload: FormData) => postForm<CsvRunResult>('/api/ingestion/csv-run', payload),
};
