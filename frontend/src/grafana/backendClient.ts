import type { SetupCheckResult } from '../utils/setupCheck';
import type {
  AlertItem,
  AnalysisRun,
  AssistantChatResponse,
  AssistantFeedback,
  AssistantFeedbackCreate,
  AssistantFeedbackReason,
  BehaviorFinding,
  CoverageReport,
  Finding,
  FindingVerdict,
  MemoryStatsResponse,
  PrometheusConnectionsResponse,
  PrometheusConnectionTestResponse,
  RecurringProblemsResponse,
  SameFixResponse,
  SeenBeforeResponse,
  Signal,
  StarterQuestions,
  TimeseriesPoint,
} from '../types';
import type { AutonomousPolicyRun } from '../autonomous/dashboardModel';
import type {
  GrafanaAnalyzerRoutingDecision,
  AutonomousPolicy,
  AutonomousPolicySaveRequest,
  AutonomousPreviewRequest,
  AutonomousPreviewResponse,
  AutonomousRunResponse,
  GrafanaAnalyzerExecution,
  GrafanaAnalysisFinding,
  GrafanaAnalysisResult,
  GrafanaAnalysisSignal,
  GrafanaBehaviorCaseCreateResponse,
  GrafanaBehaviorFinding,
  GrafanaCase,
  GrafanaCaseCreateResponse,
  GrafanaQuestion,
  GrafanaQuestionAnswer,
  CaseTicketLink,
  TicketingStatus,
  CaseTicketOperation,
  CaseTicketEvent,
  AmbiguousResolutionPayload,
} from './contracts';
import type { MetricSample } from './prometheusFrameNormalizer';

export type FindingsWindow = '1h' | '6h' | '24h' | '7d';

export type AutonomousQuestionAnswer = {
  headline: string;
  answer: string;
  priority: string;
  confidence: number;
  key_points: string[];
  evidence: Record<string, unknown>;
};

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
  analyzerExecutions?: GrafanaAnalyzerExecution[];
  /** Set for runs through a backend connection: the cluster analysed and the connection's name. */
  cluster?: string | null;
  connection?: string | null;
};

function normalizeBaseUrl(baseUrl: string) {
  return baseUrl.replace(/\/+$/, '');
}

// The plugin calls the backend straight from the browser, so the optional API token
// (OPS_SIGNALS_API_TOKEN) lives in this browser's storage - anyone using this Grafana in this
// browser can read it. See docs/security-model.md.
const API_TOKEN_STORAGE_KEY = 'opsSignals.apiToken';

export function getApiToken(): string {
  try {
    return window.localStorage.getItem(API_TOKEN_STORAGE_KEY) ?? '';
  } catch {
    return '';
  }
}

export function setApiToken(token: string) {
  try {
    if (token.trim()) window.localStorage.setItem(API_TOKEN_STORAGE_KEY, token.trim());
    else window.localStorage.removeItem(API_TOKEN_STORAGE_KEY);
  } catch {
    // Storage blocked: requests go without a token.
  }
}

function authHeaders(): Record<string, string> {
  const token = getApiToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
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
  const response = await fetch(`${normalizeBaseUrl(baseUrl)}${path}`, { headers: authHeaders() });
  if (!response.ok) {
    throw await buildRequestError(response);
  }
  return response.json() as Promise<T>;
}

async function postJson<T>(baseUrl: string, path: string, payload?: unknown): Promise<T> {
  const response = await fetch(`${normalizeBaseUrl(baseUrl)}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  if (!response.ok) {
    throw await buildRequestError(response);
  }
  return response.json() as Promise<T>;
}

async function postJsonWithTimeout<T>(baseUrl: string, path: string, payload: unknown, timeoutMs: number): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${normalizeBaseUrl(baseUrl)}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    if (!response.ok) {
      throw await buildRequestError(response);
    }
    return response.json() as Promise<T>;
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)} seconds`);
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

async function patchJson<T>(baseUrl: string, path: string, payload: unknown): Promise<T> {
  const response = await fetch(`${normalizeBaseUrl(baseUrl)}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw await buildRequestError(response);
  }
  return response.json() as Promise<T>;
}

async function deleteJson<T>(baseUrl: string, path: string): Promise<T> {
  const response = await fetch(`${normalizeBaseUrl(baseUrl)}${path}`, { method: 'DELETE', headers: authHeaders() });
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

// The plugin shows only the newest runs (the overview's execution history lists 7), and the full list
// carries every run's router/profile/findings JSON - gigabytes on a long-lived install.
export const RECENT_RUNS_LIMIT = 25;

export async function listAnalysisRuns(baseUrl: string, params: { limit?: number; service?: string; metric?: string } = {}) {
  const query = new URLSearchParams({ limit: String(params.limit ?? RECENT_RUNS_LIMIT) });
  if (params.service) query.append('service', params.service);
  if (params.metric) query.append('metric_name', params.metric);
  return fetchJson<AnalysisRun[]>(baseUrl, `/api/analysis-runs?${query}`);
}

export async function listAutonomousPolicyRuns(baseUrl: string, limit = 25) {
  return fetchJson<AutonomousPolicyRun[]>(baseUrl, `/api/autonomous/policy-runs?limit=${limit}`);
}

export async function listAutonomousPolicyRunJobs(baseUrl: string, policyRunId: string) {
  return fetchJson<Record<string, unknown>[]>(baseUrl, `/api/autonomous/policy-runs/${encodeURIComponent(policyRunId)}/jobs`);
}

export async function listFindings(baseUrl: string, params?: {
  window?: FindingsWindow;
  service?: string;
  metricName?: string;
}) {
  const search = new URLSearchParams();
  if (params?.window) search.set('window', params.window);
  if (params?.service) search.set('service', params.service);
  if (params?.metricName) search.set('metric_name', params.metricName);
  const suffix = search.toString() ? `?${search.toString()}` : '';
  return fetchJson<Finding[]>(baseUrl, `/api/findings${suffix}`);
}

export async function searchFindings(baseUrl: string, params: {
  window?: FindingsWindow;
  q?: string;
  service?: string;
  metricName?: string;
  limit?: number;
}) {
  const search = new URLSearchParams();
  search.set('window', params.window ?? '24h');
  search.set('limit', String(params.limit ?? 8));
  if (params.q) search.set('q', params.q);
  if (params.service) search.set('service', params.service);
  if (params.metricName) search.set('metric_name', params.metricName);
  return fetchJson<Finding[]>(baseUrl, `/api/findings/search?${search.toString()}`);
}

export async function answerAutonomousQuestion(baseUrl: string, payload: {
  question: string;
  policy_run_id?: string | null;
  window?: FindingsWindow;
  service?: string;
  metric_name?: string;
}) {
  return postJson<AutonomousQuestionAnswer>(baseUrl, '/api/autonomous/questions/answer', payload);
}

export async function listBehaviorFindings(baseUrl: string, params?: {
  analysisRunId?: string;
  service?: string;
}) {
  const search = new URLSearchParams();
  if (params?.analysisRunId) search.set('analysis_run_id', params.analysisRunId);
  if (params?.service) search.set('service', params.service);
  const suffix = search.toString() ? `?${search.toString()}` : '';
  return fetchJson<BehaviorFinding[]>(baseUrl, `/api/behavior-evaluations${suffix}`);
}

export async function previewAutonomousPlan(baseUrl: string, payload: AutonomousPreviewRequest) {
  return postJsonWithTimeout<AutonomousPreviewResponse>(baseUrl, '/api/autonomous/preview', payload, 120000);
}

export async function runAutonomousPlanOnce(baseUrl: string, payload: AutonomousPreviewRequest) {
  return postJson<AutonomousRunResponse>(baseUrl, '/api/autonomous/run-once', { ...payload, dry_run: false });
}

export async function listAutonomousPolicies(baseUrl: string, limit = 50) {
  return fetchJson<AutonomousPolicy[]>(baseUrl, `/api/autonomous/policies?limit=${limit}`);
}

export async function saveAutonomousPolicy(baseUrl: string, payload: AutonomousPolicySaveRequest) {
  return postJson<AutonomousPolicy>(baseUrl, '/api/autonomous/policies', payload);
}

export async function updateAutonomousPolicy(baseUrl: string, policyId: string, payload: AutonomousPolicySaveRequest) {
  return patchJson<AutonomousPolicy>(baseUrl, `/api/autonomous/policies/${encodeURIComponent(policyId)}`, payload);
}

export async function setAutonomousPolicyStatus(baseUrl: string, policyId: string, enabled: boolean) {
  return patchJson<AutonomousPolicy>(baseUrl, `/api/autonomous/policies/${encodeURIComponent(policyId)}/status`, { enabled });
}

export async function deleteAutonomousPolicy(baseUrl: string, policyId: string) {
  return deleteJson<{ deleted: boolean; id: string }>(baseUrl, `/api/autonomous/policies/${encodeURIComponent(policyId)}`);
}

export async function listAutonomousScopeOptions(baseUrl: string, labels: {
  serviceLabel: string;
  namespaceLabel: string;
  environmentLabel: string;
  window: string;
  /** Which Prometheus connection (Mimir tenant) to list values from; omitted = the default one. */
  connectionId?: string | null;
}) {
  const params = new URLSearchParams({
    service_label: labels.serviceLabel,
    namespace_label: labels.namespaceLabel,
    environment_label: labels.environmentLabel,
    window: labels.window,
  });
  if (labels.connectionId) params.set('connection_id', labels.connectionId);
  // clusters is [] for single-cluster data.
  return fetchJson<{ services: string[]; namespaces: string[]; environments: string[]; clusters?: string[]; cluster_label?: string | null }>(baseUrl, `/api/autonomous/scope-options?${params.toString()}`);
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
    start_time: signal.start_time,
    end_time: signal.end_time,
    evidence: signal.evidence ?? {},
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
    comparison_json: finding.comparison_json ?? {},
    trust: finding.trust ?? null,
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
    service: finding.service ?? null,
    case_id: finding.case_id ?? null,
  };
}

export async function runBackendAnalysis(baseUrl: string, target: {
  datasource: string;
  service: string;
  metric: string;
  from: string;
  to: string;
}): Promise<BackendPluginAnalysis> {
  const matching = await listAnalysisRuns(baseUrl, { limit: 1, service: target.service, metric: target.metric });
  const runs = matching.length ? matching : await listAnalysisRuns(baseUrl, { limit: 1 });
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

/** Label values on one backend connection, optionally only on series `match` selects in a time range. */
export async function listPrometheusLabelValues(baseUrl: string, label: string, connectionId: string, filter?: { match?: string[]; start?: string; end?: string }) {
  const params = new URLSearchParams({ label, connection_id: connectionId });
  (filter?.match ?? []).forEach((selector) => params.append('match', selector));
  if (filter?.start) params.set('start', filter.start);
  if (filter?.end) params.set('end', filter.end);
  return fetchJson<{ connection_id: string; label: string; values: string[] }>(baseUrl, `/api/prometheus/label-values?${params.toString()}`);
}

type RunSummary = {
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
  analyzer_executions?: GrafanaAnalyzerExecution[];
};

/** Loads what an analysis run produced (timeline, findings, signals, behaviors) into the plugin's result. */
async function collectRunResult(baseUrl: string, run: RunSummary, target: {
  datasource: string;
  datasourceUid?: string;
  service: string;
  metric: string;
  promql: string;
  from: string;
  to: string;
  durationMs?: number;
  cluster?: string | null;
  connection?: string | null;
}): Promise<BackendPluginAnalysis> {
  const byRun = (extra: Record<string, string> = {}) => new URLSearchParams({ service: target.service, analysis_run_id: run.analysis_run_id, ...extra }).toString();
  const [runs, timeseries, findings, signals, behaviorFindings] = await Promise.all([
    listAnalysisRuns(baseUrl),
    fetchJson<TimeseriesPoint[]>(baseUrl, `/api/timeseries?${byRun({ metric_name: target.metric, ...(target.cluster ? { cluster: target.cluster } : {}) })}`),
    fetchJson<Finding[]>(baseUrl, `/api/findings?${byRun({ metric_name: target.metric })}`),
    fetchJson<Signal[]>(baseUrl, `/api/signals?${byRun({ metric_name: target.metric })}`),
    fetchJson<BehaviorFinding[]>(baseUrl, `/api/behavior-evaluations?${byRun()}`),
  ]);

  return {
    runId: run.analysis_run_id,
    datasource: target.datasource,
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
    analyzerExecutions: run.analyzer_executions ?? [],
    cluster: target.cluster ?? null,
    connection: target.connection ?? null,
  };
}

/** Analyses one series through a backend connection (one per Mimir tenant), as the web UI's
 * Validate Data does: the backend queries it, tags the run with its cluster and connection, and
 * keeps one copy of series an HA Prometheus pair wrote twice. */
export async function runConnectionAnalysis(baseUrl: string, target: {
  connectionId: string;
  connectionName: string;
  service: string;
  metric: string;
  promql: string;
  from: string;
  to: string;
  stepSeconds: number;
  cluster?: string | null;
  startedAt?: number;
}): Promise<BackendPluginAnalysis> {
  const run = await postJsonWithTimeout<RunSummary & { connection_name?: string }>(baseUrl, '/api/analysis/prometheus', {
    connection_id: target.connectionId,
    query: target.promql,
    service: target.service,
    metric: target.metric,
    start: target.from,
    end: target.to,
    step: `${Math.max(target.stepSeconds, 1)}s`,
    execution_mode: 'persist',
  }, 120000);
  return collectRunResult(baseUrl, run, {
    datasource: run.connection_name ?? target.connectionName,
    datasourceUid: target.connectionId,
    service: target.service,
    metric: target.metric,
    promql: target.promql,
    from: target.from,
    to: target.to,
    durationMs: target.startedAt === undefined ? undefined : Math.round(performance.now() - target.startedAt),
    cluster: target.cluster,
    connection: run.connection_name ?? target.connectionName,
  });
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
  const run = await postJson<RunSummary>(baseUrl, '/api/ingestion/prometheus-run', {
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

  return collectRunResult(baseUrl, run, {
    datasource: target.datasourceName ?? target.datasourceUid,
    datasourceUid: target.datasourceUid,
    service: target.service,
    metric: target.metric,
    promql: target.promql,
    from: target.from,
    to: target.to,
    durationMs: target.durationMs,
  });
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

/** Each part of the install, whether it works and how to fix it (the Setup check). */
export async function getSetupCheck(baseUrl: string) {
  return fetchJson<SetupCheckResult>(baseUrl, '/api/setup/check');
}

/** One synthetic alert through the alerts receiver, to prove it end to end. */
export async function sendTestAlert(baseUrl: string) {
  return postJson<{ accepted?: number }>(baseUrl, '/api/integrations/alertmanager/test', {});
}

/** The backend's Prometheus connections (one per Mimir tenant or Prometheus server). */
export async function listPrometheusConnections(baseUrl: string) {
  return fetchJson<PrometheusConnectionsResponse>(baseUrl, '/api/prometheus/connections');
}

export async function testPrometheusConnection(baseUrl: string, connectionId: string) {
  return postJson<PrometheusConnectionTestResponse>(baseUrl, '/api/prometheus/test-connection', { connection_id: connectionId });
}

/** Questions worth asking about what was analysed most recently; has_data false before any run. */
export async function getStarterQuestions(baseUrl: string) {
  return fetchJson<StarterQuestions>(baseUrl, '/api/assistant/starter-questions');
}

/** "Did this answer your question?" */
export async function sendAssistantFeedback(baseUrl: string, payload: AssistantFeedbackCreate) {
  return postJson<AssistantFeedback>(baseUrl, '/api/assistant/feedback', payload);
}

/** What was wrong with an answer marked unhelpful. */
export async function updateAssistantFeedbackReason(baseUrl: string, feedbackId: number, reason: AssistantFeedbackReason) {
  return patchJson<AssistantFeedback>(baseUrl, `/api/assistant/feedback/${feedbackId}`, { reason });
}

export async function getMemoryStats(baseUrl: string) {
  return fetchJson<MemoryStatsResponse>(baseUrl, '/api/memory/stats');
}

export async function getRecurringProblems(baseUrl: string, days = 90, groupBy: 'symptom' | 'cause' = 'symptom', minOccurrences = 3) {
  return fetchJson<RecurringProblemsResponse>(baseUrl, `/api/memory/recurring-problems?days=${days}&min_occurrences=${minOccurrences}&group_by=${groupBy}`);
}

/** Which imported past incidents were detected while they happened. */
export async function getMonitoringCoverage(baseUrl: string, days = 365) {
  return fetchJson<CoverageReport>(baseUrl, `/api/memory/coverage?days=${days}`);
}

/** Alerts received (Alertmanager and other sources) since `since`, with matched changes and links. */
export async function listAlerts(baseUrl: string, params: { since?: string; limit?: number } = {}) {
  const search = new URLSearchParams();
  if (params.since) search.set('since', params.since);
  if (params.limit) search.set('limit', String(params.limit));
  const suffix = search.toString() ? `?${search.toString()}` : '';
  return fetchJson<AlertItem[]>(baseUrl, `/api/alerts${suffix}`);
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

export async function createCaseFromBehavior(baseUrl: string, behaviorFindingId: number) {
  return postJson<GrafanaBehaviorCaseCreateResponse>(baseUrl, `/api/cases/behaviors/${behaviorFindingId}/create`);
}

/** The team's answer to "Was this real?"; returns the finding with its trust recomputed. */
export async function sendFindingFeedback(baseUrl: string, findingId: number, verdict: FindingVerdict) {
  return postJson<Finding>(baseUrl, `/api/findings/${findingId}/feedback`, { verdict });
}

/** Past cases with the same cause and fix as this case, on any service, and how each fix held. */
export async function getCaseSameFix(baseUrl: string, caseId: number) {
  return fetchJson<SameFixResponse>(baseUrl, `/api/cases/${caseId}/same-fix`);
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

/** Past cases (Qdrant case memory) that resemble a persisted finding, plus how familiar it is. */
export async function getFindingSeenBefore(baseUrl: string, findingId: number) {
  return fetchJson<SeenBeforeResponse>(baseUrl, `/api/findings/${findingId}/seen-before`);
}

export async function indexCaseMemory(baseUrl: string, caseId: number) {
  return postJson<{ case_id: number; memory_status: string; indexed_at?: string }>(baseUrl, `/api/cases/${caseId}/memory/index`);
}

export async function createCaseTicket(baseUrl: string, caseId: number, provider?: string) {
  return postJson<CaseTicketOperation>(baseUrl, `/api/cases/${caseId}/ticket/create`, { provider });
}

export async function getTicketingStatus(baseUrl: string) {
  return fetchJson<TicketingStatus>(baseUrl, '/api/integrations/ticketing/status');
}

export async function getCaseTicket(baseUrl: string, caseId: number, provider?: string) {
  const query = provider ? `?provider=${encodeURIComponent(provider)}` : '';
  return fetchJson<CaseTicketLink | null>(baseUrl, `/api/cases/${caseId}/ticket${query}`);
}

export async function syncCaseTicket(baseUrl: string, caseId: number, provider?: string) {
  return postJson<CaseTicketOperation>(baseUrl, `/api/cases/${caseId}/ticket/sync`, { provider });
}

export async function resolveCaseTicketAmbiguity(baseUrl: string, caseId: number, payload: AmbiguousResolutionPayload) {
  return postJson<any>(baseUrl, `/api/cases/${caseId}/ticket/resolve-ambiguity`, payload);
}

export async function getCaseTicketEvents(baseUrl: string, caseId: number) {
  return fetchJson<CaseTicketEvent[]>(baseUrl, `/api/cases/${caseId}/ticket/events`);
}

