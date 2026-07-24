import type { AnalysisRun, AssistantChatResponse, BehaviorFinding, Finding, Signal, TimeseriesPoint } from '../types';
import type {
  GrafanaAnalyzerRoutingDecision,
  GrafanaAnalysisFinding,
  GrafanaAnalysisResult,
  GrafanaAnalysisSignal,
  GrafanaBehaviorFinding,
  GrafanaCase,
  GrafanaCaseCreateResponse,
  GrafanaQuestion,
  GrafanaQuestionAnswer,
} from './contracts';
import type { MetricSample } from './prometheusFrameNormalizer';

export type BackendPluginAnalysis = {
  runId: string;
  datasource: string;
  datasourceUid?: string;
  service: string;
  metric: string;
  promql?: string;
  from: string;
  to: string;
  status: 'idle' | 'running' | 'complete' | 'error';
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

function normalizeBaseUrl(baseUrl: string) {
  return baseUrl.replace(/\/+$/, '');
}

async function buildRequestError(response: Response) {
  let detail = '';
  try {
    const contentType = response.headers.get('content-type') ?? '';
    if (contentType.includes('application/json')) {
      const payload = await response.json();
      if (typeof payload?.detail === 'string') {
        detail = payload.detail;
      } else if (Array.isArray(payload?.detail)) {
        detail = payload.detail.map((item: unknown) => JSON.stringify(item)).join(', ');
      } else if (payload?.message) {
        detail = String(payload.message);
      }
    } else {
      const text = await response.text();
      if (text) detail = text;
    }
  } catch {
    detail = '';
  }

  return new Error(detail ? `Request failed: ${response.status} - ${detail}` : `Request failed: ${response.status}`);
}

async function fetchJson<T>(baseUrl: string, path: string): Promise<T> {
  const response = await fetch(`${normalizeBaseUrl(baseUrl)}${path}`);
  if (!response.ok) {
    throw await buildRequestError(response);
  }
  return response.json() as Promise<T>;
}

async function postJson<T>(baseUrl: string, path: string, payload?: unknown): Promise<T> {
  const response = await fetch(`${normalizeBaseUrl(baseUrl)}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  if (!response.ok) {
    throw await buildRequestError(response);
  }
  return response.json() as Promise<T>;
}

async function patchJson<T>(baseUrl: string, path: string, payload: unknown): Promise<T> {
  const response = await fetch(`${normalizeBaseUrl(baseUrl)}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw await buildRequestError(response);
  }
  return response.json() as Promise<T>;
}

export async function listServices(baseUrl: string) {
  return fetchJson<string[]>(baseUrl, '/api/services');
}

export async function listMetrics(baseUrl: string, service: string) {
  return fetchJson<string[]>(baseUrl, `/api/services/${encodeURIComponent(service)}/metrics`);
}

export async function listAnalysisRuns(baseUrl: string) {
  return fetchJson<AnalysisRun[]>(baseUrl, '/api/analysis-runs');
}

function pickLatestRun(runs: AnalysisRun[], service: string, metric: string) {
  return runs.find((run) => run.service === service && run.metric_name === metric) ?? runs[0] ?? null;
}

function toGrafanaSignal(signal: Signal): GrafanaAnalysisSignal {
  return {
    id: signal.id,
    analyzer_id: signal.analyzer_id ?? 'ops-signals-backend',
    signal_type: signal.signal_type,
    summary: signal.summary ?? 'Signal detected.',
    severity: signal.severity,
    confidence: signal.confidence ?? undefined,
    importance_score: signal.importance_score,
  };
}

function toGrafanaFinding(finding: Finding): GrafanaAnalysisFinding {
  return {
    id: finding.id ?? 0,
    title: finding.title,
    summary: finding.summary,
    category: finding.category,
    health_status: finding.health_status,
    importance_score: finding.importance_score,
    investigation_priority: finding.investigation_priority,
    signal_ids: finding.signal_ids ?? [],
  };
}

function toGrafanaBehaviorFinding(finding: BehaviorFinding): GrafanaBehaviorFinding {
  return {
    id: finding.id,
    title: finding.title,
    summary: finding.summary,
    severity: finding.severity,
    confidence: finding.confidence,
    correlation: finding.correlation_json,
  };
}

export async function runBackendAnalysis(baseUrl: string, target: {
  datasource: string;
  service: string;
  metric: string;
  from: string;
  to: string;
}): Promise<BackendPluginAnalysis> {
  const runs = await fetchJson<AnalysisRun[]>(baseUrl, '/api/analysis-runs');
  const latestRun = pickLatestRun(runs, target.service, target.metric);
  const runId = latestRun?.id ?? `ops-signals-${Date.now()}`;
  const analysisRunId = latestRun?.id ?? undefined;

  const timeseriesParams = new URLSearchParams({
    service: target.service,
    metric_name: target.metric,
  });
  if (target.from) timeseriesParams.append('start_time', target.from);
  if (target.to) timeseriesParams.append('end_time', target.to);
  if (analysisRunId) timeseriesParams.append('analysis_run_id', analysisRunId);

  const findingsParams = new URLSearchParams({
    service: target.service,
    metric_name: target.metric,
  });
  if (analysisRunId) findingsParams.append('analysis_run_id', analysisRunId);

  const behaviorParams = new URLSearchParams({
    service: target.service,
  });
  if (analysisRunId) behaviorParams.append('analysis_run_id', analysisRunId);

  const [timeseries, findings, behaviorFindings] = await Promise.all([
    fetchJson<TimeseriesPoint[]>(baseUrl, `/api/timeseries?${timeseriesParams.toString()}`),
    fetchJson<Finding[]>(baseUrl, `/api/findings?${findingsParams.toString()}`),
    fetchJson<BehaviorFinding[]>(baseUrl, `/api/behavior-evaluations?${behaviorParams.toString()}`),
  ]);

  const summary =
    timeseries.length > 0
      ? `Backend returned ${timeseries.length} samples, ${findings.length} findings, and ${behaviorFindings.length} behavior findings.`
      : `Backend returned ${findings.length} findings and ${behaviorFindings.length} behavior findings for the selected context.`;

  return {
    runId,
    datasource: target.datasource,
    service: target.service,
    metric: target.metric,
    from: target.from,
    to: target.to,
    status: 'complete',
    summary,
    signals: findings.flatMap((finding) =>
      finding.signal_ids.map((signalId) =>
        toGrafanaSignal({
          id: signalId,
          signal_type: 'backend-linked',
          analyzer_id: 'ops-signals-backend',
          metric_name: target.metric,
          service: target.service,
          severity: finding.health_status,
          confidence: finding.importance_score,
          importance_score: finding.importance_score,
          summary: finding.summary,
          evidence: { source: 'backend', finding_id: finding.id },
          analysis_run_id: runId,
        })
      )
    ),
    findings: findings.map(toGrafanaFinding),
    behaviorFindings: behaviorFindings.map(toGrafanaBehaviorFinding),
    timeseries,
    analysisRuns: runs,
  };
}

export async function runPrometheusSampleAnalysis(baseUrl: string, target: {
  datasourceUid: string;
  datasourceName?: string;
  service: string;
  metric: string;
  promql: string;
  from: string;
  to: string;
  stepSeconds: number;
  samples: MetricSample[];
  seriesCount: number;
  sampleCount: number;
  warnings: string[];
  durationMs: number;
}): Promise<BackendPluginAnalysis> {
  const run = await postJson<{
    analysis_run_id: string;
    sample_count: number;
    series_count: number;
    signal_count: number;
    findings_count: number;
    behavior_findings_count: number;
    warnings: string[];
    analyzer_selection_mode?: string;
    analyzer_routing?: GrafanaAnalyzerRoutingDecision[];
    executed_analyzers?: string[];
  }>(baseUrl, '/api/ingestion/prometheus-run', {
    provider: 'prometheus',
    datasource_uid: target.datasourceUid,
    datasource_name: target.datasourceName,
    service: target.service,
    metric_name: target.metric,
    promql: target.promql,
    from: target.from,
    to: target.to,
    step_seconds: target.stepSeconds,
    samples: target.samples,
    series_count: target.seriesCount,
    sample_count: target.sampleCount,
    max_series: 20,
    max_samples_per_series: 10000,
    warnings: target.warnings,
  });

  const timeseriesParams = new URLSearchParams({
    service: target.service,
    metric_name: target.metric,
    analysis_run_id: run.analysis_run_id,
  });
  const findingsParams = new URLSearchParams({
    service: target.service,
    metric_name: target.metric,
    analysis_run_id: run.analysis_run_id,
  });
  const signalsParams = new URLSearchParams({
    service: target.service,
    metric_name: target.metric,
    analysis_run_id: run.analysis_run_id,
  });
  const behaviorParams = new URLSearchParams({
    service: target.service,
    analysis_run_id: run.analysis_run_id,
  });

  const [runs, timeseries, findings, signals, behaviorFindings] = await Promise.all([
    fetchJson<AnalysisRun[]>(baseUrl, '/api/analysis-runs'),
    fetchJson<TimeseriesPoint[]>(baseUrl, `/api/timeseries?${timeseriesParams.toString()}`),
    fetchJson<Finding[]>(baseUrl, `/api/findings?${findingsParams.toString()}`),
    fetchJson<Signal[]>(baseUrl, `/api/signals?${signalsParams.toString()}`),
    fetchJson<BehaviorFinding[]>(baseUrl, `/api/behavior-evaluations?${behaviorParams.toString()}`),
  ]);

  return {
    runId: run.analysis_run_id,
    datasource: target.datasourceName ?? target.datasourceUid,
    datasourceUid: target.datasourceUid,
    service: target.service,
    metric: target.metric,
    promql: target.promql,
    from: target.from,
    to: target.to,
    status: 'complete',
    summary: `Prometheus returned ${run.sample_count.toLocaleString()} samples across ${run.series_count.toLocaleString()} series. Ops Signals produced ${run.signal_count} signals, ${run.findings_count} findings, and ${run.behavior_findings_count} behavior findings.`,
    signals: signals.map(toGrafanaSignal),
    findings: findings.map(toGrafanaFinding),
    behaviorFindings: behaviorFindings.map(toGrafanaBehaviorFinding),
    timeseries,
    analysisRuns: runs,
    seriesCount: run.series_count,
    sampleCount: run.sample_count,
    warnings: run.warnings,
    durationMs: target.durationMs,
    analyzerSelectionMode: run.analyzer_selection_mode,
    analyzerRouting: run.analyzer_routing ?? [],
    executedAnalyzers: run.executed_analyzers ?? [],
  };
}

export async function listAvailableQuestions(baseUrl: string, target: {
  service: string;
  metric: string;
  analysisRunId: string;
}) {
  const params = new URLSearchParams({
    service: target.service,
    metric_name: target.metric,
    analysis_run_id: target.analysisRunId,
  });
  return fetchJson<GrafanaQuestion[]>(baseUrl, `/api/questions/available?${params.toString()}`);
}

export async function answerQuestion(baseUrl: string, target: {
  questionId: string;
  service: string;
  metric: string;
  analysisRunId: string;
}) {
  return postJson<GrafanaQuestionAnswer>(baseUrl, '/api/questions/answer', {
    question_id: target.questionId,
    service: target.service,
    metric_name: target.metric,
    analysis_run_id: target.analysisRunId,
  });
}

export async function askAssistantWithMemory(baseUrl: string, target: {
  message: string;
  caseId?: number | null;
  conversationId?: string | null;
}) {
  return postJson<AssistantChatResponse>(baseUrl, '/api/assistant/chat', {
    message: target.message,
    case_id: target.caseId ?? null,
    conversation_id: target.conversationId ?? null,
    top_k: 5,
    minimum_score: 0.4,
    same_service_only: false,
  });
}

export async function resetTestingOperationalData(baseUrl: string) {
  return postJson<{
    status: string;
    deleted_rows: Record<string, number>;
    vector_memory: Record<string, unknown>;
  }>(baseUrl, '/api/testing/reset-operational-data', {
    confirm: 'RESET_OPS_SIGNALS_TEST_DATA',
    clear_vector_memory: true,
  });
}

export async function createCaseFromFinding(baseUrl: string, findingId: number) {
  return postJson<GrafanaCaseCreateResponse>(baseUrl, `/api/cases/findings/${findingId}/create`);
}

export async function getCase(baseUrl: string, caseId: number) {
  return fetchJson<GrafanaCase>(baseUrl, `/api/cases/${caseId}`);
}

export async function listCases(baseUrl: string, params?: {
  service?: string;
  metricName?: string;
  limit?: number;
}) {
  const search = new URLSearchParams();
  if (params?.service) search.set('service', params.service);
  if (params?.metricName) search.set('metric_name', params.metricName);
  if (params?.limit) search.set('limit', String(params.limit));
  const suffix = search.toString() ? `?${search.toString()}` : '';
  return fetchJson<GrafanaCase[]>(baseUrl, `/api/cases${suffix}`);
}

export async function updateCaseInvestigation(baseUrl: string, caseId: number, payload: {
  investigation_status: string;
  investigation_note?: string;
}) {
  return patchJson<GrafanaCase>(baseUrl, `/api/cases/${caseId}/investigation`, payload);
}

export async function updateCaseRca(baseUrl: string, caseId: number, payload: {
  root_cause_status: string;
  root_cause_summary?: string | null;
  root_cause_confidence?: number | null;
  root_cause_verified: boolean;
}) {
  return patchJson<GrafanaCase>(baseUrl, `/api/cases/${caseId}/rca`, payload);
}

export async function updateCaseResolution(baseUrl: string, caseId: number, payload: {
  outcome_status: string;
  outcome_summary?: string | null;
  corrective_action?: string | null;
  learning_outcome_status?: string | null;
  root_cause_category?: string | null;
  resolution_summary?: string | null;
  resolved_by?: string | null;
}) {
  return patchJson<GrafanaCase>(baseUrl, `/api/cases/${caseId}/resolution`, payload);
}

export async function indexCaseMemory(baseUrl: string, caseId: number) {
  return postJson<{ case_id: number; memory_status: string; indexed_at?: string }>(baseUrl, `/api/cases/${caseId}/memory/index`);
}
