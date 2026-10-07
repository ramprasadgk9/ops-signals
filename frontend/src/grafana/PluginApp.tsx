import React from 'react';
import { useEffect, useMemo, useState } from 'react';
import { answerAutonomousQuestion, createCaseFromFinding, createCaseTicket, getApiToken, getCase, getCaseTicket, listAnalysisRuns, listAutonomousPolicies, listAutonomousPolicyRuns, listAutonomousScopeOptions, listBehaviorFindings, listCases, listFindings, previewAutonomousPlan, runAutonomousPlanOnce, runPrometheusSampleAnalysis, saveAutonomousPolicy, searchFindings, setApiToken, setAutonomousPolicyStatus, syncCaseTicket, updateAutonomousPolicy, type AutonomousQuestionAnswer, type FindingsWindow } from './backendClient';
import { buildTimeRange, calculateIntervalMs, createRelativeTimeRange, formatDateTimeLocal, parseDateTimeLocal, readGrafanaTimeRange } from './grafanaTimeRange';
import {
  discoverMetricNames,
  discoverLabelValues,
  discoverServiceValues,
  listPrometheusDatasources,
  queryPrometheusDatasource,
  type PrometheusDatasourceRef,
} from './grafanaPrometheus';
import { InvestigationDrawer, PanelPreview } from './PanelPreview';
import { Card, Field, styles } from './plainUi';
import { PluginBreakdownDisclosure, PluginBreakdownSection, PluginScopeChip } from './PluginBreakdown';
import { PluginSeenBefore } from './PluginSeenBefore';
import { findingBreakdown } from '../utils/findingBreakdown';
import { findingLevel } from '../utils/findingLevel';
import { buildMetricQuery, type MetricMode } from './prometheusQueryBuilder';
import { normalizePrometheusFrames } from './prometheusFrameNormalizer';
import type { AutonomousPlanItem, AutonomousPolicy, AutonomousPreviewResponse, AutonomousRunResponse, CaseTicketLink, CaseTicketOperation, GrafanaAnalysisResult, GrafanaCase, GrafanaCaseCreateResponse, GrafanaQueryTarget, MonitoringCategory } from './contracts';
import type { AnalysisRun, BehaviorFinding, Finding } from '../types';
import { buildAutonomousPreviewRequest, filterPreviewRows, previewRowExplanation } from './autonomousPreviewModel';
import { buildAutonomousDashboardData, formatMatchedRule, type AutonomousDashboardData, type AutonomousPolicyRun, type AutonomousSelectionSummary } from '../autonomous/dashboardModel';

const defaultTarget: GrafanaQueryTarget = {
  datasource: 'Prometheus',
  service: '',
  metric: '',
  timeRange: {
    from: '',
    to: '',
  },
};

const backendOptions = [
  { label: 'Grafana stack backend (:8002)', value: 'http://localhost:8002' },
  { label: 'Standalone app backend (:8001)', value: 'http://localhost:8001' },
  { label: 'Host backend from Docker (:8002)', value: 'http://host.docker.internal:8002' },
];

const timePresets = [
  { label: 'Last 30m', hours: 0.5 },
  { label: 'Last 1h', hours: 1 },
  { label: 'Last 6h', hours: 6 },
  { label: 'Last 24h', hours: 24 },
];

type PluginMode = 'interactive' | 'autonomous';
type AutonomousUiStage = 'configure' | 'preview_loading' | 'preview_ready' | 'preview_error' | 'running' | 'run_complete' | 'run_error' | 'overview_loading' | 'overview_ready' | 'overview_empty' | 'overview_error';

type OverviewEndpointError = {
  component: string;
  apiFunction: string;
  endpoint: string;
  url: string;
  message: string;
};

type AutonomousAskState = {
  question: string;
  answer: AutonomousQuestionAnswer | null;
  isLoading: boolean;
  error: string;
  setQuestion: (value: string) => void;
  ask: (question?: string) => Promise<void>;
};

type AutonomousFindingsLookupState = {
  window: FindingsWindow;
  query: string;
  service: string;
  metricName: string;
  findings: Finding[];
  isLoading: boolean;
  error: string;
  setWindow: (value: FindingsWindow) => void;
  setQuery: (value: string) => void;
  setService: (value: string) => void;
  setMetricName: (value: string) => void;
  search: () => Promise<void>;
  askAboutFinding: (finding: Finding) => Promise<void>;
};

const monitorCategories = [
  { id: 'performance', title: 'Performance', detail: 'Latency, throughput, request rate' },
  { id: 'capacity', title: 'Capacity', detail: 'CPU, memory, disk, saturation' },
  { id: 'availability', title: 'Availability', detail: 'Errors, success rate, saturation' },
  { id: 'reliability', title: 'Reliability', detail: 'Exceptions, retries, timeouts' },
  { id: 'infrastructure', title: 'Infrastructure', detail: 'Nodes, containers, volumes' },
  { id: 'messaging', title: 'Messaging', detail: 'Kafka lag, queues, publish rate' },
  { id: 'kubernetes', title: 'Kubernetes', detail: 'Pods, deployments, restarts' },
  { id: 'custom', title: 'Custom', detail: 'Define custom constraints' },
] satisfies Array<{ id: MonitoringCategory; title: string; detail: string }>;

export function PluginApp(_props: unknown) {
  const defaultBackendUrl = import.meta.env.VITE_OPS_SIGNALS_BACKEND_URL ?? 'http://localhost:8002';
  const [activeMode, setActiveMode] = useState<PluginMode>('interactive');
  const [target, setTarget] = useState<GrafanaQueryTarget>(defaultTarget);
  const [result, setResult] = useState<GrafanaAnalysisResult | null>(null);
  const [backendUrl, setBackendUrl] = useState(defaultBackendUrl);
  const [prometheusDatasources, setPrometheusDatasources] = useState<PrometheusDatasourceRef[]>([]);
  const [selectedPrometheusUid, setSelectedPrometheusUid] = useState('');
  const [serviceLabel, setServiceLabel] = useState('service');
  const [metricMode, setMetricMode] = useState<MetricMode>('metric');
  const [timeRange, setTimeRange] = useState(readGrafanaTimeRange);
  const [timeFromInput, setTimeFromInput] = useState(() => formatDateTimeLocal(readGrafanaTimeRange().from));
  const [timeToInput, setTimeToInput] = useState(() => formatDateTimeLocal(readGrafanaTimeRange().to));
  const [services, setServices] = useState<string[]>([]);
  const [namespaces, setNamespaces] = useState<string[]>([]);
  const [metrics, setMetrics] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [stage, setStage] = useState('');
  const [isLoadingContext, setIsLoadingContext] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [overviewRuns, setOverviewRuns] = useState<AnalysisRun[]>([]);
  const [overviewFindings, setOverviewFindings] = useState<Finding[]>([]);
  const [overviewBehaviorFindings, setOverviewBehaviorFindings] = useState<BehaviorFinding[]>([]);
  const [overviewCases, setOverviewCases] = useState<GrafanaCase[]>([]);
  const [overviewPolicyRuns, setOverviewPolicyRuns] = useState<AutonomousPolicyRun[]>([]);
  const [overviewError, setOverviewError] = useState('');
  const [overviewEndpointErrors, setOverviewEndpointErrors] = useState<OverviewEndpointError[]>([]);
  const [isLoadingOverview, setIsLoadingOverview] = useState(false);
  const [autonomousEnvironment, setAutonomousEnvironment] = useState('production');
  const [autonomousAllServices, setAutonomousAllServices] = useState(true);
  const [autonomousServices, setAutonomousServices] = useState<string[]>([]);
  const [autonomousAllNamespaces, setAutonomousAllNamespaces] = useState(true);
  const [autonomousNamespaces, setAutonomousNamespaces] = useState<string[]>([]);
  const [namespaceLabel, setNamespaceLabel] = useState('namespace');
  const [environmentLabel, setEnvironmentLabel] = useState('env');
  const [selectedCategories, setSelectedCategories] = useState<MonitoringCategory[]>(['performance', 'capacity', 'availability']);
  const [customExplicitMetrics, setCustomExplicitMetrics] = useState('');
  const [customIncludePatterns, setCustomIncludePatterns] = useState('');
  const [customExcludePatterns, setCustomExcludePatterns] = useState('.*_info$,.*_created$');
  const [executionInterval, setExecutionInterval] = useState('1m');
  const [analysisWindow, setAnalysisWindow] = useState('24h');
  const [maxMetricsPerRun, setMaxMetricsPerRun] = useState('500');
  const [maxParallelJobs, setMaxParallelJobs] = useState('20');
  const [previewResult, setPreviewResult] = useState<AutonomousPreviewResponse | null>(null);
  const [previewError, setPreviewError] = useState('');
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isPreviewingPolicy, setIsPreviewingPolicy] = useState(false);
  const [previewPolicyError, setPreviewPolicyError] = useState('');
  const [autonomousRunResult, setAutonomousRunResult] = useState<AutonomousRunResponse | null>(null);
  const [autonomousRunError, setAutonomousRunError] = useState('');
  const [isAutonomousRunning, setIsAutonomousRunning] = useState(false);
  const [autonomousInvestigationFinding, setAutonomousInvestigationFinding] = useState<Finding | null>(null);
  const [autonomousInvestigationMode, setAutonomousInvestigationMode] = useState<'investigate' | 'evidence'>('investigate');
  const [autonomousCaseResult, setAutonomousCaseResult] = useState<GrafanaCaseCreateResponse | null>(null);
  const [autonomousCaseDetails, setAutonomousCaseDetails] = useState<GrafanaCase | null>(null);
  const [autonomousCaseError, setAutonomousCaseError] = useState('');
  const [isCreatingAutonomousCase, setIsCreatingAutonomousCase] = useState(false);
  const [autonomousAskQuestion, setAutonomousAskQuestion] = useState('');
  const [autonomousAskAnswer, setAutonomousAskAnswer] = useState<AutonomousQuestionAnswer | null>(null);
  const [autonomousAskError, setAutonomousAskError] = useState('');
  const [isAutonomousAsking, setIsAutonomousAsking] = useState(false);
  const [autonomousLookupWindow, setAutonomousLookupWindow] = useState<FindingsWindow>('24h');
  const [autonomousLookupQuery, setAutonomousLookupQuery] = useState('');
  const [autonomousLookupService, setAutonomousLookupService] = useState('');
  const [autonomousLookupMetric, setAutonomousLookupMetric] = useState('');
  const [autonomousLookupFindings, setAutonomousLookupFindings] = useState<Finding[]>([]);
  const [autonomousLookupError, setAutonomousLookupError] = useState('');
  const [isAutonomousLookupLoading, setIsAutonomousLookupLoading] = useState(false);

  useEffect(() => {
    try {
      const nextDatasources = listPrometheusDatasources();
      setPrometheusDatasources(nextDatasources);
      setSelectedPrometheusUid((current) => current || nextDatasources[0]?.uid || '');
      if (nextDatasources.length === 0) {
        setError('No Prometheus datasource is configured in Grafana.');
      }
    } catch {
      setError('Failed to load Grafana Prometheus datasources.');
    }
  }, []);

  useEffect(() => {
    let active = true;
    if (!selectedPrometheusUid) return;
    setMetrics([]);
    setServices([]);
    setNamespaces([]);
    setIsLoadingContext(true);
    setError('');

    Promise.all([
      discoverServiceValues(selectedPrometheusUid, serviceLabel),
      discoverLabelValues(selectedPrometheusUid, namespaceLabel),
      discoverMetricNames(selectedPrometheusUid),
    ])
      .then(([nextServices, nextNamespaces, nextMetrics]) => {
        if (!active) return;
        setServices(nextServices);
        setNamespaces(nextNamespaces);
        setMetrics(nextMetrics.slice(0, 500));
      })
      .catch(() => {
        if (active) setError('Could not discover services or metrics from Prometheus. You can still type values manually.');
      })
      .finally(() => {
        if (active) setIsLoadingContext(false);
      });

    return () => {
      active = false;
    };
  }, [selectedPrometheusUid, serviceLabel, namespaceLabel]);

  useEffect(() => {
    const refreshRange = () => setTimeRange(readGrafanaTimeRange());
    window.addEventListener('popstate', refreshRange);
    return () => window.removeEventListener('popstate', refreshRange);
  }, []);

  useEffect(() => {
    setTimeFromInput(formatDateTimeLocal(timeRange.from));
    setTimeToInput(formatDateTimeLocal(timeRange.to));
  }, [timeRange]);

  async function refreshAutonomousOverview(active = true) {
    setIsLoadingOverview(true);
    setOverviewError('');
    setOverviewEndpointErrors([]);
    const overviewRequests = [
      { component: 'Discovery & Selection / Execution History', apiFunction: 'listAnalysisRuns', endpoint: '/api/analysis-runs', run: () => listAnalysisRuns(backendUrl) },
      { component: 'Top Findings / Behavior Distribution', apiFunction: 'listFindings', endpoint: '/api/findings?window=24h', run: () => listFindings(backendUrl, { window: '24h' }) },
      { component: 'Behavior Findings', apiFunction: 'listBehaviorFindings', endpoint: '/api/behavior-evaluations', run: () => listBehaviorFindings(backendUrl) },
      { component: 'Recent Cases', apiFunction: 'listCases', endpoint: '/api/cases?limit=10', run: () => listCases(backendUrl, { limit: 10 }) },
      { component: 'Autonomous run metadata', apiFunction: 'listAutonomousPolicyRuns', endpoint: '/api/autonomous/policy-runs?limit=25', run: () => listAutonomousPolicyRuns(backendUrl, 25) },
    ] as const;
    try {
      const results = await Promise.allSettled(overviewRequests.map((request) => request.run()));
      if (!active) return;

      const errors: OverviewEndpointError[] = [];
      results.forEach((result, index) => {
        if (result.status === 'fulfilled') return;
        const request = overviewRequests[index];
        errors.push({
          component: request.component,
          apiFunction: request.apiFunction,
          endpoint: request.endpoint,
          url: `${backendUrl.replace(/\/+$/, '')}${request.endpoint}`,
          message: result.reason instanceof Error ? result.reason.message : 'Request failed.',
        });
      });

      if (results[0].status === 'fulfilled') setOverviewRuns(results[0].value as AnalysisRun[]);
      if (results[1].status === 'fulfilled') setOverviewFindings(results[1].value as Finding[]);
      if (results[2].status === 'fulfilled') setOverviewBehaviorFindings(results[2].value as BehaviorFinding[]);
      if (results[3].status === 'fulfilled') setOverviewCases(results[3].value as GrafanaCase[]);
      if (results[4].status === 'fulfilled') setOverviewPolicyRuns(results[4].value as AutonomousPolicyRun[]);

      if (errors.length) {
        setOverviewEndpointErrors(errors);
        setOverviewError('Autonomous monitoring summary could not be loaded.');
      }
    } catch {
      if (!active) return;
      setOverviewError('Autonomous monitoring summary could not be loaded.');
    } finally {
      if (active) setIsLoadingOverview(false);
    }
  }

  useEffect(() => {
    let active = true;
    if (activeMode !== 'autonomous' || !backendUrl) return;
    refreshAutonomousOverview(active);

    return () => {
      active = false;
    };
  }, [activeMode, backendUrl]);

  useEffect(() => {
    let active = true;
    if (activeMode !== 'autonomous' || !backendUrl) return;
    listAutonomousScopeOptions(backendUrl, { serviceLabel, namespaceLabel, environmentLabel, window: analysisWindow })
      .then((options) => {
        if (!active) return;
        setServices(options.services);
        setNamespaces(options.namespaces);
      })
      .catch(() => {
        // Keep Grafana-discovered values as a graceful fallback.
      });
    return () => {
      active = false;
    };
  }, [activeMode, backendUrl, serviceLabel, namespaceLabel, environmentLabel, analysisWindow]);

  const selectedDatasource = useMemo(
    () => prometheusDatasources.find((datasource) => datasource.uid === selectedPrometheusUid),
    [prometheusDatasources, selectedPrometheusUid]
  );
  const backendReady = useMemo(() => Boolean(backendUrl), [backendUrl]);
  const ready = Boolean(selectedPrometheusUid && target.service && target.metric);
  const timeRangeValid = timeRange.from.getTime() < timeRange.to.getTime();
  const latestAutonomousPolicyRunId = overviewPolicyRuns[0]?.policy_run_id ?? overviewPolicyRuns[0]?.id ?? autonomousRunResult?.policy_run_id ?? null;

  function setRange(nextFrom: Date, nextTo: Date) {
    setTimeRange(buildTimeRange(nextFrom, nextTo));
  }

  async function askAutonomousQuestion(question?: string) {
    const nextQuestion = (question ?? autonomousAskQuestion).trim();
    if (!nextQuestion) return;
    if (question) setAutonomousAskQuestion(question);
    setIsAutonomousAsking(true);
    setAutonomousAskError('');
    try {
      const answer = await answerAutonomousQuestion(backendUrl, {
        question: nextQuestion,
        policy_run_id: latestAutonomousPolicyRunId,
        window: autonomousLookupWindow,
        service: autonomousLookupService.trim() || undefined,
        metric_name: autonomousLookupMetric.trim() || undefined,
      });
      setAutonomousAskAnswer(answer);
    } catch {
      setAutonomousAskError('Could not answer from autonomous run evidence. Check the backend URL and retry.');
    } finally {
      setIsAutonomousAsking(false);
    }
  }

  async function searchAutonomousFindings() {
    setIsAutonomousLookupLoading(true);
    setAutonomousLookupError('');
    try {
      const nextFindings = await searchFindings(backendUrl, {
        window: autonomousLookupWindow,
        q: autonomousLookupQuery.trim() || undefined,
        service: autonomousLookupService.trim() || undefined,
        metricName: autonomousLookupMetric.trim() || undefined,
        limit: 8,
      });
      setAutonomousLookupFindings(nextFindings);
    } catch {
      setAutonomousLookupError('Could not search stored findings. Check the backend URL and retry.');
    } finally {
      setIsAutonomousLookupLoading(false);
    }
  }

  function applyPreset(hours: number) {
    const preset = createRelativeTimeRange(hours);
    setTimeRange(preset);
  }

  function applyCustomRange() {
    const nextFrom = parseDateTimeLocal(timeFromInput);
    const nextTo = parseDateTimeLocal(timeToInput);
    if (!nextFrom || !nextTo) {
      setError('Enter a valid custom time range.');
      return;
    }
    if (nextFrom.getTime() >= nextTo.getTime()) {
      setError('Time range is invalid. "From" must be earlier than "To".');
      return;
    }
    setError('');
    setRange(nextFrom, nextTo);
  }

  return (
    <main style={styles.shell}>
      <div style={styles.rowBetween}>
        <div>
          <h1 style={{ margin: 0 }}>Ops Signals</h1>
          <p style={{ ...styles.muted, margin: '6px 0 0' }}>Operational changes detected from the selected Grafana metric and time range.</p>
        </div>
        <div style={styles.row}>
          <span style={{ ...styles.chip, color: backendReady ? '#3fcf8e' : '#ffb357' }}>● {backendReady ? 'Backend connected' : isLoadingContext ? 'Backend loading' : 'Backend waiting'}</span>
          <span style={{ ...styles.chip, color: '#3fcf8e' }}>● Prometheus ready</span>
          <span style={{ ...styles.chip, color: '#3fcf8e' }}>● Case memory enabled</span>
        </div>
      </div>

      {error && <div style={styles.alert}>{error}</div>}
      {stage && <div style={styles.alert}>{stage}</div>}

      <ModeTabs activeMode={activeMode} onChange={setActiveMode} />

      {activeMode === 'interactive' ? (
        <>
          <InteractiveAnalysisCard
            prometheusDatasources={prometheusDatasources}
            selectedPrometheusUid={selectedPrometheusUid}
            setSelectedPrometheusUid={setSelectedPrometheusUid}
            backendUrl={backendUrl}
            setBackendUrl={setBackendUrl}
            target={target}
            setTarget={setTarget}
            services={services}
            metrics={metrics}
            metricMode={metricMode}
            setMetricMode={setMetricMode}
            serviceLabel={serviceLabel}
            setServiceLabel={setServiceLabel}
            timeRange={timeRange}
            timeFromInput={timeFromInput}
            setTimeFromInput={setTimeFromInput}
            timeToInput={timeToInput}
            setTimeToInput={setTimeToInput}
            applyPreset={applyPreset}
            applyCustomRange={applyCustomRange}
            ready={ready}
            timeRangeValid={timeRangeValid}
            isRunning={isRunning}
            onClearResult={() => setResult(null)}
            onRun={async () => {
              if (!ready || !timeRangeValid) return;
              setIsRunning(true);
              setError('');
              setStage('Resolving Prometheus datasource');
              const startedAt = performance.now();
              try {
                const promql = buildMetricQuery({
                  metric: target.metric,
                  mode: metricMode,
                  service: target.service,
                  serviceLabel,
                });
                const intervalMs = calculateIntervalMs(timeRange);
                setStage(`Querying Prometheus: ${promql}`);
                const frames = await queryPrometheusDatasource({
                  datasourceUid: selectedPrometheusUid,
                  promql,
                  range: timeRange,
                  intervalMs,
                });
                setStage('Normalizing Prometheus samples');
                const normalized = normalizePrometheusFrames(frames as any[], {
                  metricName: target.metric,
                  service: target.service,
                  maxSeries: 20,
                  maxSamplesPerSeries: 10000,
                });
                setStage('Running Ops Signals analyzers');
                const backendResult = await runPrometheusSampleAnalysis(backendUrl, {
                  datasourceUid: selectedPrometheusUid,
                  datasourceName: selectedDatasource?.name,
                  service: target.service,
                  metric: target.metric,
                  promql,
                  from: timeRange.from.toISOString(),
                  to: timeRange.to.toISOString(),
                  stepSeconds: Math.max(Math.round(intervalMs / 1000), 1),
                  samples: normalized.samples,
                  seriesCount: normalized.seriesCount,
                  sampleCount: normalized.sampleCount,
                  warnings: normalized.warnings,
                  durationMs: Math.round(performance.now() - startedAt),
                });
                setResult(backendResult);
              } catch (runError) {
                const message = runError instanceof Error ? runError.message : 'Unknown error';
                setError(`${stage || 'Analysis'} failed. ${message}`);
              } finally {
                setIsRunning(false);
                setStage('');
              }
            }}
          />
          <PanelPreview result={result} backendUrl={backendUrl} />
        </>
      ) : (
        <AutonomousAnalysisView
          backendUrl={backendUrl}
          setBackendUrl={setBackendUrl}
          selectedPrometheusUid={selectedPrometheusUid}
          setSelectedPrometheusUid={setSelectedPrometheusUid}
          prometheusDatasources={prometheusDatasources}
          services={services}
          namespaces={namespaces}
          runs={overviewRuns}
          findings={overviewFindings}
          behaviorFindings={overviewBehaviorFindings}
          cases={overviewCases}
          policyRuns={overviewPolicyRuns}
          isLoading={isLoadingOverview}
          error={overviewError}
          endpointErrors={overviewEndpointErrors}
          environment={autonomousEnvironment}
          setEnvironment={setAutonomousEnvironment}
          allServices={autonomousAllServices}
          setAllServices={setAutonomousAllServices}
          selectedServices={autonomousServices}
          setSelectedServices={setAutonomousServices}
          allNamespaces={autonomousAllNamespaces}
          setAllNamespaces={setAutonomousAllNamespaces}
          selectedNamespaces={autonomousNamespaces}
          setSelectedNamespaces={setAutonomousNamespaces}
          serviceLabel={serviceLabel}
          setServiceLabel={setServiceLabel}
          namespaceLabel={namespaceLabel}
          setNamespaceLabel={setNamespaceLabel}
          environmentLabel={environmentLabel}
          setEnvironmentLabel={setEnvironmentLabel}
          selectedCategories={selectedCategories}
          setSelectedCategories={setSelectedCategories}
          customExplicitMetrics={customExplicitMetrics}
          setCustomExplicitMetrics={setCustomExplicitMetrics}
          customIncludePatterns={customIncludePatterns}
          setCustomIncludePatterns={setCustomIncludePatterns}
          customExcludePatterns={customExcludePatterns}
          setCustomExcludePatterns={setCustomExcludePatterns}
          executionInterval={executionInterval}
          setExecutionInterval={setExecutionInterval}
          analysisWindow={analysisWindow}
          setAnalysisWindow={setAnalysisWindow}
          maxMetricsPerRun={maxMetricsPerRun}
          setMaxMetricsPerRun={setMaxMetricsPerRun}
          maxParallelJobs={maxParallelJobs}
          setMaxParallelJobs={setMaxParallelJobs}
          previewResult={previewResult}
          previewError={previewError}
          isPreviewing={isPreviewing}
          isPreviewingPolicy={isPreviewingPolicy}
          previewPolicyError={previewPolicyError}
          runResult={autonomousRunResult}
          runError={autonomousRunError}
          isRunningOnce={isAutonomousRunning}
          investigationFinding={autonomousInvestigationFinding}
          investigationMode={autonomousInvestigationMode}
          caseResult={autonomousCaseResult}
          caseDetails={autonomousCaseDetails}
          caseError={autonomousCaseError}
          isCreatingCase={isCreatingAutonomousCase}
          askState={{
            question: autonomousAskQuestion,
            answer: autonomousAskAnswer,
            isLoading: isAutonomousAsking,
            error: autonomousAskError,
            setQuestion: setAutonomousAskQuestion,
            ask: askAutonomousQuestion,
          }}
          findingsLookupState={{
            window: autonomousLookupWindow,
            query: autonomousLookupQuery,
            service: autonomousLookupService,
            metricName: autonomousLookupMetric,
            findings: autonomousLookupFindings,
            isLoading: isAutonomousLookupLoading,
            error: autonomousLookupError,
            setWindow: setAutonomousLookupWindow,
            setQuery: setAutonomousLookupQuery,
            setService: setAutonomousLookupService,
            setMetricName: setAutonomousLookupMetric,
            search: searchAutonomousFindings,
            askAboutFinding: (finding) => askAutonomousQuestion(`What should I investigate first for ${finding.service} / ${finding.metric_name}?`),
          }}
          onRetryOverview={() => refreshAutonomousOverview(true)}
          onBackToConfigure={() => {
            setPreviewResult(null);
            setPreviewError('');
            setAutonomousRunResult(null);
            setAutonomousRunError('');
            setAutonomousInvestigationFinding(null);
            setAutonomousCaseResult(null);
            setAutonomousCaseDetails(null);
            setAutonomousCaseError('');
          }}
          onInvestigateInteractive={(finding) => {
            setTarget((current) => ({
              ...current,
              service: finding.service || current.service,
              metric: finding.metric_name || current.metric,
            }));
            setActiveMode('interactive');
            setAutonomousInvestigationFinding(null);
          }}
          onOpenInvestigation={(finding, mode) => {
            setAutonomousInvestigationFinding(finding);
            setAutonomousInvestigationMode(mode);
            setAutonomousCaseError('');
          }}
          onCloseInvestigation={() => {
            setAutonomousInvestigationFinding(null);
            setAutonomousCaseError('');
          }}
          onCreateCase={async (finding) => {
            if (!finding.id) {
              setAutonomousCaseError('A persisted finding id is required before a case can be created.');
              return;
            }
            setIsCreatingAutonomousCase(true);
            setAutonomousCaseError('');
            try {
              const createdCase = await createCaseFromFinding(backendUrl, finding.id);
              setAutonomousCaseResult(createdCase);
              setAutonomousCaseDetails(await getCase(backendUrl, createdCase.case_id));
              setAutonomousInvestigationFinding(finding);
              setAutonomousInvestigationMode('investigate');
              await refreshAutonomousOverview(true);
            } catch {
              setAutonomousCaseError('Could not create an investigation case for this finding.');
            } finally {
              setIsCreatingAutonomousCase(false);
            }
          }}
          onPreview={async () => {
            if (!selectedCategories.length) {
              setPreviewError('Select at least one monitoring category.');
              return;
            }
            setIsPreviewing(true);
            setPreviewError('');
            setAutonomousRunResult(null);
            setAutonomousRunError('');
            setAutonomousInvestigationFinding(null);
            setAutonomousCaseResult(null);
            setAutonomousCaseDetails(null);
            setAutonomousCaseError('');
            try {
              const response = await previewAutonomousPlan(backendUrl, buildAutonomousPreviewRequest({
                backend: 'grafana-stack',
                environment: autonomousEnvironment,
                allServices: autonomousAllServices,
                selectedServices: autonomousServices,
                allNamespaces: autonomousAllNamespaces,
                selectedNamespaces: autonomousNamespaces,
                serviceLabel,
                namespaceLabel,
                environmentLabel,
                selectedCategories,
                executionInterval,
                analysisWindow,
                maxMetricsPerRun,
                maxParallelJobs,
                customExplicitMetrics,
                customIncludePatterns,
                customExcludePatterns,
              }));
              setPreviewResult(response);
            } catch {
              setPreviewError('Metric plan could not be loaded. Check that the selected backend is reachable, reduce the scope if needed, then try again.');
            } finally {
              setIsPreviewing(false);
            }
          }}
          onPreviewPolicy={async (policy) => {
            setIsPreviewingPolicy(true);
            setPreviewPolicyError('');
            try {
              const response = await previewAutonomousPlan(backendUrl, {
                datasource: 'prometheus',
                backend: policy.backend,
                scope: policy.scope,
                monitoring_selection: policy.monitoring_selection,
                monitoring_categories: policy.monitoring_selection.categories,
                execution: policy.execution,
                custom_constraints: {
                  include_patterns: policy.monitoring_selection.custom_constraints?.include_patterns ?? [],
                  exclude_patterns: policy.monitoring_selection.custom_constraints?.exclude_patterns ?? [],
                  required_labels: policy.monitoring_selection.custom_constraints?.required_labels ?? {},
                  explicit_metrics: policy.monitoring_selection.custom_constraints?.explicit_metrics ?? [],
                },
              });
              setPreviewResult(response);
            } catch {
              setPreviewPolicyError('Metric plan could not be loaded. Check that the selected backend is reachable, then try again.');
            } finally {
              setIsPreviewingPolicy(false);
            }
          }}
          onRunOnce={async () => {
            if (!previewResult?.planned_jobs) {
              setAutonomousRunError('Preview a metric plan with at least one planned job before starting analysis.');
              return;
            }
            setIsAutonomousRunning(true);
            setAutonomousRunError('');
            try {
              const response = await runAutonomousPlanOnce(backendUrl, buildAutonomousPreviewRequest({
                backend: 'grafana-stack',
                environment: autonomousEnvironment,
                allServices: autonomousAllServices,
                selectedServices: autonomousServices,
                allNamespaces: autonomousAllNamespaces,
                selectedNamespaces: autonomousNamespaces,
                serviceLabel,
                namespaceLabel,
                environmentLabel,
                selectedCategories,
                executionInterval,
                analysisWindow,
                maxMetricsPerRun,
                maxParallelJobs,
                customExplicitMetrics,
                customIncludePatterns,
                customExcludePatterns,
              }));
              setAutonomousRunResult(response);
              setPreviewResult(response.preview);
              await refreshAutonomousOverview(true);
            } catch {
              setAutonomousRunError('Autonomous analysis could not be completed. Check the backend connection and selected metric plan, then try again.');
            } finally {
              setIsAutonomousRunning(false);
            }
          }}
        />
      )}
    </main>
  );
}

function ModeTabs({ activeMode, onChange }: { activeMode: PluginMode; onChange: (mode: PluginMode) => void }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10, maxWidth: 720 }}>
      <ModeTab
        active={activeMode === 'interactive'}
        title="Interactive Analysis"
        subtitle="Investigate one metric"
        tone="#5794f2"
        onClick={() => onChange('interactive')}
      />
      <ModeTab
        active={activeMode === 'autonomous'}
        title="Autonomous Analysis"
        subtitle="Analyze many metrics automatically"
        tone="#3fcf8e"
        onClick={() => onChange('autonomous')}
      />
    </div>
  );
}

function ModeTab({ active, title, subtitle, tone, onClick }: { active: boolean; title: string; subtitle: string; tone: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        border: `1px solid ${active ? tone : 'rgba(204, 204, 220, 0.18)'}`,
        borderRadius: 8,
        padding: '12px 16px',
        background: active ? `linear-gradient(135deg, ${tone}22, rgba(24, 27, 31, 0.82))` : 'rgba(24, 27, 31, 0.54)',
        color: 'inherit',
        cursor: 'pointer',
        textAlign: 'left',
      }}
    >
      <div style={{ color: tone, fontWeight: 800 }}>{title}</div>
      <div style={{ ...styles.helperText, marginTop: 3 }}>{subtitle}</div>
    </button>
  );
}

type InteractiveCardProps = {
  prometheusDatasources: PrometheusDatasourceRef[];
  selectedPrometheusUid: string;
  setSelectedPrometheusUid: (value: string) => void;
  backendUrl: string;
  setBackendUrl: (value: string) => void;
  target: GrafanaQueryTarget;
  setTarget: React.Dispatch<React.SetStateAction<GrafanaQueryTarget>>;
  services: string[];
  metrics: string[];
  metricMode: MetricMode;
  setMetricMode: (value: MetricMode) => void;
  serviceLabel: string;
  setServiceLabel: (value: string) => void;
  timeRange: ReturnType<typeof readGrafanaTimeRange>;
  timeFromInput: string;
  setTimeFromInput: (value: string) => void;
  timeToInput: string;
  setTimeToInput: (value: string) => void;
  applyPreset: (hours: number) => void;
  applyCustomRange: () => void;
  ready: boolean;
  timeRangeValid: boolean;
  isRunning: boolean;
  onClearResult: () => void;
  onRun: () => Promise<void>;
};

/** Only needed when the backend sets OPS_SIGNALS_API_TOKEN. Saved in this browser on blur; requests
 * made after that carry it. */
function ApiTokenField() {
  const [token, setToken] = useState(getApiToken);
  return (
    <Field label="API token (optional)">
      <input
        style={styles.input}
        type="password"
        autoComplete="off"
        value={token}
        placeholder="Only if the backend requires one"
        onChange={(event) => setToken(event.target.value)}
        onBlur={() => setApiToken(token)}
      />
    </Field>
  );
}

function InteractiveAnalysisCard(props: InteractiveCardProps) {
  return (
    <Card>
      <div style={{ ...styles.rowBetween, alignItems: 'flex-start', marginBottom: 14 }}>
        <div>
          <h2 style={{ margin: 0, color: '#73bf69' }}>Interactive Analysis</h2>
          <p style={{ ...styles.muted, margin: '5px 0 0' }}>Select a service, metric, and time range to investigate.</p>
        </div>
        <span style={styles.chip}>One metric per run</span>
      </div>
      <div style={styles.toolbar}>
        <Field label="Data source">
          <select
            style={styles.input}
            value={props.selectedPrometheusUid}
            onChange={(event) => {
              props.setSelectedPrometheusUid(event.target.value);
              props.onClearResult();
            }}
          >
            <option value="">{props.prometheusDatasources.length ? 'Select Prometheus' : 'No Prometheus datasource'}</option>
            {props.prometheusDatasources.map((datasource) => (
              <option key={datasource.uid} value={datasource.uid}>
                {datasource.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Ops Signals backend">
          <select
            style={styles.input}
            value={props.backendUrl}
            onChange={(event) => {
              props.setBackendUrl(event.target.value);
              props.onClearResult();
              props.setTarget((current) => ({ ...current, service: '', metric: '' }));
            }}
          >
            {backendOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>
        <ApiTokenField />
        <Field label="Service">
          <input
            style={styles.input}
            list="ops-signals-services"
            value={props.target.service}
            placeholder={`Value for label "${props.serviceLabel}"`}
            onChange={(event) => props.setTarget((current) => ({ ...current, service: event.target.value }))}
          />
          <datalist id="ops-signals-services">
            {props.services.map((service) => (
              <option key={service} value={service} />
            ))}
          </datalist>
        </Field>
        <Field label="Metric">
          <input
            style={styles.input}
            list="ops-signals-metrics"
            value={props.target.metric}
            placeholder={props.metricMode === 'metric' ? 'Metric name' : 'PromQL expression'}
            onChange={(event) => props.setTarget((current) => ({ ...current, metric: event.target.value }))}
          />
          <datalist id="ops-signals-metrics">
            {props.metrics.map((metric) => (
              <option key={metric} value={metric} />
            ))}
          </datalist>
        </Field>
        <Field label="Mode">
          <select style={styles.input} value={props.metricMode} onChange={(event) => props.setMetricMode(event.target.value as MetricMode)}>
            <option value="metric">Metric</option>
            <option value="promql">PromQL expression</option>
          </select>
        </Field>
        <Field label="Service label">
          <input style={styles.input} value={props.serviceLabel} onChange={(event) => props.setServiceLabel(event.target.value)} />
        </Field>
        <Field label="Time range">
          <div style={{ display: 'grid', gap: 8 }}>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {timePresets.map((preset) => (
                <button key={preset.label} type="button" style={{ ...styles.chip, background: 'transparent', color: 'inherit', cursor: 'pointer' }} onClick={() => props.applyPreset(preset.hours)}>
                  {preset.label}
                </button>
              ))}
            </div>
            <input style={{ ...styles.input, ...styles.inputReadOnly }} value={props.timeRange.display} readOnly />
            <input style={styles.input} type="datetime-local" value={props.timeFromInput} onChange={(event) => props.setTimeFromInput(event.target.value)} />
            <input style={styles.input} type="datetime-local" value={props.timeToInput} onChange={(event) => props.setTimeToInput(event.target.value)} />
            <button type="button" style={styles.button} onClick={props.applyCustomRange}>
              Apply custom range
            </button>
            <div style={styles.helperText}>Use quick presets for testing, or enter a custom local start and end time directly here.</div>
          </div>
        </Field>
        <button
          type="button"
          style={props.ready && props.timeRangeValid && !props.isRunning ? styles.button : { ...styles.button, ...styles.buttonDisabled }}
          onClick={props.onRun}
          disabled={!props.ready || !props.timeRangeValid || props.isRunning}
        >
          {props.isRunning ? 'Running...' : 'Run Analysis'}
        </button>
      </div>
    </Card>
  );
}

function AutonomousAnalysisView({
  backendUrl,
  setBackendUrl,
  selectedPrometheusUid,
  setSelectedPrometheusUid,
  prometheusDatasources,
  services,
  namespaces,
  runs,
  findings,
  behaviorFindings,
  cases,
  policyRuns,
  isLoading,
  error,
  endpointErrors,
  environment,
  setEnvironment,
  allServices,
  setAllServices,
  selectedServices,
  setSelectedServices,
  allNamespaces,
  setAllNamespaces,
  selectedNamespaces,
  setSelectedNamespaces,
  serviceLabel,
  setServiceLabel,
  namespaceLabel,
  setNamespaceLabel,
  environmentLabel,
  setEnvironmentLabel,
  selectedCategories,
  setSelectedCategories,
  customExplicitMetrics,
  setCustomExplicitMetrics,
  customIncludePatterns,
  setCustomIncludePatterns,
  customExcludePatterns,
  setCustomExcludePatterns,
  executionInterval,
  setExecutionInterval,
  analysisWindow,
  setAnalysisWindow,
  maxMetricsPerRun,
  setMaxMetricsPerRun,
  maxParallelJobs,
  setMaxParallelJobs,
  previewResult,
  previewError,
  isPreviewing,
  isPreviewingPolicy,
  previewPolicyError,
  runResult,
  runError,
  isRunningOnce,
  investigationFinding,
  investigationMode,
  caseResult,
  caseDetails,
  caseError,
  isCreatingCase,
  askState,
  findingsLookupState,
  onRetryOverview,
  onBackToConfigure,
  onInvestigateInteractive,
  onOpenInvestigation,
  onCloseInvestigation,
  onCreateCase,
  onPreview,
  onPreviewPolicy,
  onRunOnce,
}: {
  backendUrl: string;
  setBackendUrl: (value: string) => void;
  selectedPrometheusUid: string;
  setSelectedPrometheusUid: (value: string) => void;
  prometheusDatasources: PrometheusDatasourceRef[];
  services: string[];
  namespaces: string[];
  runs: AnalysisRun[];
  findings: Finding[];
  behaviorFindings: BehaviorFinding[];
  cases: GrafanaCase[];
  policyRuns: AutonomousPolicyRun[];
  isLoading: boolean;
  error: string;
  endpointErrors: OverviewEndpointError[];
  environment: string;
  setEnvironment: (value: string) => void;
  allServices: boolean;
  setAllServices: (value: boolean) => void;
  selectedServices: string[];
  setSelectedServices: (value: string[]) => void;
  allNamespaces: boolean;
  setAllNamespaces: (value: boolean) => void;
  selectedNamespaces: string[];
  setSelectedNamespaces: (value: string[]) => void;
  serviceLabel: string;
  setServiceLabel: (value: string) => void;
  namespaceLabel: string;
  setNamespaceLabel: (value: string) => void;
  environmentLabel: string;
  setEnvironmentLabel: (value: string) => void;
  selectedCategories: MonitoringCategory[];
  setSelectedCategories: (value: MonitoringCategory[]) => void;
  customExplicitMetrics: string;
  setCustomExplicitMetrics: (value: string) => void;
  customIncludePatterns: string;
  setCustomIncludePatterns: (value: string) => void;
  customExcludePatterns: string;
  setCustomExcludePatterns: (value: string) => void;
  executionInterval: string;
  setExecutionInterval: (value: string) => void;
  analysisWindow: string;
  setAnalysisWindow: (value: string) => void;
  maxMetricsPerRun: string;
  setMaxMetricsPerRun: (value: string) => void;
  maxParallelJobs: string;
  setMaxParallelJobs: (value: string) => void;
  previewResult: AutonomousPreviewResponse | null;
  previewError: string;
  isPreviewing: boolean;
  isPreviewingPolicy: boolean;
  previewPolicyError: string;
  runResult: AutonomousRunResponse | null;
  runError: string;
  isRunningOnce: boolean;
  investigationFinding: Finding | null;
  investigationMode: 'investigate' | 'evidence';
  caseResult: GrafanaCaseCreateResponse | null;
  caseDetails: GrafanaCase | null;
  caseError: string;
  isCreatingCase: boolean;
  askState: AutonomousAskState;
  findingsLookupState: AutonomousFindingsLookupState;
  onRetryOverview: () => void;
  onBackToConfigure: () => void;
  onInvestigateInteractive: (finding: Finding) => void;
  onOpenInvestigation: (finding: Finding, mode: 'investigate' | 'evidence') => void;
  onCloseInvestigation: () => void;
  onCreateCase: (finding: Finding) => Promise<void>;
  onPreview: () => Promise<void>;
  onPreviewPolicy: (policy: AutonomousPolicy) => Promise<void>;
  onRunOnce: () => Promise<void>;
}) {
  const [previewStatusFilter, setPreviewStatusFilter] = useState<'all' | 'planned' | 'excluded'>('all');
  const [previewCategoryFilter, setPreviewCategoryFilter] = useState<string>('all');
  const [previewConceptFilter, setPreviewConceptFilter] = useState<string>('all');
  const [expandedPreviewMetric, setExpandedPreviewMetric] = useState<string | null>(null);

  // Scheduled-policy state: local to this view, same as the preview filters above - fetched
  // straight from the backend rather than prop-drilled through PluginApp, since it doesn't need
  // to be shared with any sibling view.
  const [activePolicy, setActivePolicy] = useState<AutonomousPolicy | null>(null);
  const [isLoadingPolicy, setIsLoadingPolicy] = useState(false);
  const [policyLoadError, setPolicyLoadError] = useState('');
  const [isEditingSchedule, setIsEditingSchedule] = useState(false);
  const [isSavingSchedule, setIsSavingSchedule] = useState(false);
  const [isTogglingSchedule, setIsTogglingSchedule] = useState(false);
  const [scheduleError, setScheduleError] = useState('');
  const [scheduleMode, setScheduleMode] = useState<'run_once' | 'scheduled'>('run_once');
  const [scheduleMinutes, setScheduleMinutes] = useState(30);
  const [forceOverview, setForceOverview] = useState(false);

  useEffect(() => {
    let active = true;
    if (!backendUrl) return;
    setIsLoadingPolicy(true);
    setPolicyLoadError('');
    listAutonomousPolicies(backendUrl)
      .then((policies) => {
        if (active) setActivePolicy(policies[0] ?? null);
      })
      .catch(() => {
        if (active) setPolicyLoadError('Could not load your scheduled policy. Your schedule may still be running - this is a fetch problem, not a sign it was removed.');
      })
      .finally(() => {
        if (active) setIsLoadingPolicy(false);
      });
    return () => {
      active = false;
    };
  }, [backendUrl]);

  const refreshActivePolicy = () => {
    setIsLoadingPolicy(true);
    setPolicyLoadError('');
    listAutonomousPolicies(backendUrl)
      .then((policies) => setActivePolicy(policies[0] ?? null))
      .catch(() => setPolicyLoadError('Could not load your scheduled policy. Your schedule may still be running - this is a fetch problem, not a sign it was removed.'))
      .finally(() => setIsLoadingPolicy(false));
  };

  const handleSaveSchedule = async () => {
    setIsSavingSchedule(true);
    setScheduleError('');
    try {
      const request = buildAutonomousPreviewRequest({
        backend: 'grafana-stack',
        environment,
        allServices,
        selectedServices,
        allNamespaces,
        selectedNamespaces,
        serviceLabel,
        namespaceLabel,
        environmentLabel,
        selectedCategories,
        executionInterval,
        analysisWindow,
        maxMetricsPerRun,
        maxParallelJobs,
        customExplicitMetrics,
        customIncludePatterns,
        customExcludePatterns,
      });
      const payload = {
        name: 'Production coverage',
        datasource: request.datasource,
        backend: request.backend,
        scope: request.scope,
        monitoring_selection: request.monitoring_selection!,
        execution: request.execution,
        schedule_minutes: scheduleMode === 'scheduled' ? scheduleMinutes : null,
      };
      const saved = activePolicy ? await updateAutonomousPolicy(backendUrl, activePolicy.id, payload) : await saveAutonomousPolicy(backendUrl, payload);
      setActivePolicy(saved);
      setIsEditingSchedule(false);
    } catch {
      setScheduleError('Could not save this schedule. Check that the backend is reachable and try again.');
    } finally {
      setIsSavingSchedule(false);
    }
  };

  const handlePauseSchedule = async () => {
    if (!activePolicy) return;
    setIsTogglingSchedule(true);
    try {
      setActivePolicy(await setAutonomousPolicyStatus(backendUrl, activePolicy.id, false));
    } catch {
      setScheduleError('Could not pause this schedule.');
    } finally {
      setIsTogglingSchedule(false);
    }
  };

  const handleResumeSchedule = async () => {
    if (!activePolicy) return;
    setIsTogglingSchedule(true);
    try {
      setActivePolicy(await setAutonomousPolicyStatus(backendUrl, activePolicy.id, true));
    } catch {
      setScheduleError('Could not resume this schedule.');
    } finally {
      setIsTogglingSchedule(false);
    }
  };

  const handleBackToConfigure = () => {
    setForceOverview(false);
    onBackToConfigure();
  };

  const applyPolicyToForm = (policy: AutonomousPolicy) => {
    setEnvironment(policy.scope.environment ?? 'production');
    setServiceLabel(policy.scope.service_label);
    setNamespaceLabel(policy.scope.namespace_label);
    setEnvironmentLabel(policy.scope.environment_label);
    setAllServices(policy.scope.all_services);
    setSelectedServices(policy.scope.services);
    setAllNamespaces(policy.scope.all_namespaces);
    setSelectedNamespaces(policy.scope.namespaces);
    setSelectedCategories(policy.monitoring_selection.categories);
    setCustomExplicitMetrics((policy.monitoring_selection.custom_constraints?.explicit_metrics ?? []).join(','));
    setCustomIncludePatterns((policy.monitoring_selection.custom_constraints?.include_patterns ?? []).join(','));
    setCustomExcludePatterns((policy.monitoring_selection.custom_constraints?.exclude_patterns ?? []).join(','));
    setExecutionInterval(policy.execution.interval);
    setAnalysisWindow(policy.execution.analysis_window);
    setMaxMetricsPerRun(String(policy.execution.max_metrics_per_run));
    setMaxParallelJobs(String(policy.execution.max_parallel_jobs));
    setScheduleMode(policy.schedule_minutes ? 'scheduled' : 'run_once');
    if (policy.schedule_minutes) setScheduleMinutes(policy.schedule_minutes);
  };

  const handleEditSchedule = () => {
    if (activePolicy) applyPolicyToForm(activePolicy);
    setIsEditingSchedule(true);
  };
  const dashboardData = buildAutonomousDashboardData({
    findings,
    cases,
    analysisRuns: runs,
    behaviorFindings,
    policyRuns,
    previewResult,
    runResult,
    findingHref: () => '#top-findings',
    caseHref: (caseItem) => `#case-${caseItem.id}`,
  });
  const previewRows = filterPreviewRows(previewResult?.items ?? [], previewStatusFilter, previewCategoryFilter, previewConceptFilter);
  const canPreview = Boolean(selectedPrometheusUid && backendUrl && selectedCategories.length);
  const canRunOnce = Boolean(previewResult?.planned_jobs && !isRunningOnce);
  const hasCompletedAutonomousRun = Boolean(
    runResult?.status === 'completed' ||
    runResult?.status === 'partial' ||
    forceOverview
  );
  const hasFailedAutonomousRun = Boolean(
    runResult?.status === 'failed'
  );
  const hasOverviewData = Boolean(
    findings.length ||
    cases.length ||
    runs.length ||
    policyRuns.length ||
    runResult?.executed_jobs ||
    runResult?.planned_jobs
  );
  const overviewStage: AutonomousUiStage = isLoading
    ? 'overview_loading'
    : error
      ? 'overview_error'
      : hasOverviewData
        ? 'overview_ready'
        : 'overview_empty';
  const uiStage: AutonomousUiStage = isRunningOnce
    ? 'running'
    : isPreviewing
      ? 'preview_loading'
      : previewError
        ? 'preview_error'
        : runError || hasFailedAutonomousRun
            ? 'run_error'
            : hasCompletedAutonomousRun
              ? overviewStage
              : previewResult
                ? 'preview_ready'
                : 'configure';
  const dashboardState = uiStage === 'overview_loading' ? 'loading' : uiStage === 'overview_error' ? 'error' : 'ready';
  const showConfigure = ['configure', 'preview_loading', 'preview_ready', 'preview_error', 'run_error'].includes(uiStage);
  const toggleCategory = (category: MonitoringCategory) => {
    if (selectedCategories.includes(category)) {
      setSelectedCategories(selectedCategories.filter((item) => item !== category));
    } else {
      setSelectedCategories([...selectedCategories, category]);
    }
  };
  const readMultiSelect = (event: React.ChangeEvent<HTMLSelectElement>) => Array.from(event.target.selectedOptions).map((option) => option.value);

  const autonomousTab: 'configure' | 'overview' = uiStage.startsWith('overview') ? 'overview' : 'configure';

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div style={{ display: 'flex', gap: 8 }}>
        <button
          type="button"
          style={autonomousTab === 'configure' ? { ...styles.button, background: '#3fcf8e', color: '#08130e' } : styles.button}
          onClick={handleBackToConfigure}
        >
          Configure
        </button>
        <button
          type="button"
          style={autonomousTab === 'overview' ? { ...styles.button, background: '#3fcf8e', color: '#08130e' } : styles.button}
          onClick={() => setForceOverview(true)}
          title="View findings, run history, and coverage details - available even before a run has completed in this session."
        >
          Overview
        </button>
      </div>
      {policyLoadError ? (
        <div style={{ ...styles.alert, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
          <span>{policyLoadError}</span>
          <button type="button" style={styles.button} onClick={refreshActivePolicy} disabled={isLoadingPolicy}>
            {isLoadingPolicy ? 'Retrying...' : 'Retry'}
          </button>
        </div>
      ) : null}
      {showConfigure ? (
      <Card>
        {activePolicy && !isEditingSchedule ? (
          <div>
            <div style={{ ...styles.rowBetween, alignItems: 'flex-start', marginBottom: 14, flexWrap: 'wrap', gap: 10 }}>
              <div>
                <span style={{ ...styles.chip, color: activePolicy.enabled ? '#3fcf8e' : 'rgba(204, 204, 220, 0.72)', marginBottom: 8, display: 'inline-block' }}>
                  {activePolicy.enabled ? '● Scheduled · Active' : 'Scheduled · Paused'}
                </span>
                <h2 style={{ margin: 0 }}>{activePolicy.name}</h2>
                <p style={{ ...styles.muted, margin: '5px 0 0' }}>
                  {activePolicy.monitoring_selection.categories.join(', ')} &middot; every {activePolicy.schedule_minutes ? `${activePolicy.schedule_minutes}m` : 'n/a'}
                </p>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button type="button" style={styles.button} onClick={handleEditSchedule}>Edit</button>
                {activePolicy.enabled ? (
                  <button
                    type="button"
                    style={{ ...styles.button, background: 'rgba(204, 204, 220, 0.08)', border: '1px solid rgba(204, 204, 220, 0.28)' }}
                    disabled={isTogglingSchedule}
                    onClick={handlePauseSchedule}
                    title="Stop scheduled runs. The schedule is kept and can be resumed."
                  >
                    {isTogglingSchedule ? 'Pausing...' : 'Pause'}
                  </button>
                ) : (
                  <button type="button" style={styles.button} disabled={isTogglingSchedule} onClick={handleResumeSchedule}>
                    {isTogglingSchedule ? 'Resuming...' : 'Resume'}
                  </button>
                )}
              </div>
            </div>
            {scheduleError ? <div style={{ ...styles.alert, marginBottom: 12 }}>{scheduleError}</div> : null}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12, paddingTop: 14, borderTop: '1px solid rgba(204, 204, 220, 0.14)' }}>
              <div>
                <div style={styles.label}>Last run</div>
                <div>{activePolicy.last_run_status ?? 'Not run yet'}</div>
              </div>
              <div>
                <div style={styles.label}>Next run</div>
                <div>{activePolicy.enabled ? (activePolicy.next_run_at ? new Date(activePolicy.next_run_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : 'n/a') : 'Paused'}</div>
              </div>
              <div>
                <div style={styles.label}>Health</div>
                <div style={{ color: activePolicy.consecutive_failures > 0 ? '#ff7381' : '#3fcf8e' }}>
                  {activePolicy.consecutive_failures > 0 ? `${activePolicy.consecutive_failures} failed in a row` : 'Healthy'}
                </div>
              </div>
              <div>
                <div style={styles.label}>Max metrics / run</div>
                <div>{activePolicy.execution.max_metrics_per_run}</div>
              </div>
            </div>
          </div>
        ) : (
        <>
        <div style={{ ...styles.rowBetween, alignItems: 'flex-start', marginBottom: 14 }}>
          <div>
            <h2 style={{ margin: 0, color: '#3fcf8e' }}>Configure</h2>
            <p style={{ ...styles.muted, margin: '5px 0 0' }}>
              Configure the monitoring scope, preview the planned metrics, then run once or schedule it to run automatically.
            </p>
          </div>
          <span style={{ ...styles.chip, color: '#3fcf8e' }}>{scheduleMode === 'scheduled' ? 'Scheduled' : 'Run once'}</span>
        </div>
        {activePolicy && isEditingSchedule ? (
          <button type="button" style={{ ...styles.button, marginBottom: 12 }} onClick={() => setIsEditingSchedule(false)}>Cancel edit</button>
        ) : null}
        <div style={{ ...styles.toolbar, gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
          <Field label="Data source">
            <select style={styles.input} value={selectedPrometheusUid} onChange={(event) => setSelectedPrometheusUid(event.target.value)}>
              <option value="">{prometheusDatasources.length ? 'Select Prometheus' : 'No Prometheus datasource'}</option>
              {prometheusDatasources.map((datasource) => (
                <option key={datasource.uid} value={datasource.uid}>
                  {datasource.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Backend">
            <select style={styles.input} value={backendUrl} onChange={(event) => setBackendUrl(event.target.value)}>
              {backendOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </Field>
          <ApiTokenField />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 0.35fr) minmax(320px, 1fr) minmax(220px, 0.35fr)', gap: 14, marginTop: 16 }}>
          <div style={panelStyle('#73bf69')}>
            <h3 style={sectionTitleStyle}>1. Analysis Scope</h3>
            <Field label="Environment">
              <select style={styles.input} value={environment} onChange={(event) => setEnvironment(event.target.value)}>
                <option value="production">Production</option>
                <option value="staging">Staging</option>
                <option value="all">All environments</option>
              </select>
            </Field>
            <Field label="Environment label">
              <input style={styles.input} value={environmentLabel} onChange={(event) => setEnvironmentLabel(event.target.value)} />
            </Field>
            <Field label="Service label">
              <input style={styles.input} value={serviceLabel} onChange={(event) => setServiceLabel(event.target.value)} />
            </Field>
            <Field label="Services">
              <label style={{ ...styles.row, marginBottom: 8 }}>
                <input type="checkbox" checked={allServices} onChange={(event) => setAllServices(event.target.checked)} />
                <span>All discovered services</span>
              </label>
              <select style={{ ...styles.input, minHeight: 92 }} multiple disabled={allServices} value={selectedServices} onChange={(event) => setSelectedServices(readMultiSelect(event))}>
                {services.slice(0, 100).map((service) => (
                  <option key={service} value={service}>
                    {service}
                  </option>
                ))}
              </select>
              {!services.length && <div style={styles.helperText}>No service values discovered yet. Check the service label or datasource.</div>}
            </Field>
            <Field label="Namespace label">
              <input style={styles.input} value={namespaceLabel} onChange={(event) => setNamespaceLabel(event.target.value)} />
            </Field>
            <Field label="Namespaces">
              <label style={{ ...styles.row, marginBottom: 8 }}>
                <input type="checkbox" checked={allNamespaces} onChange={(event) => setAllNamespaces(event.target.checked)} />
                <span>All namespaces</span>
              </label>
              <select style={{ ...styles.input, minHeight: 92 }} multiple disabled={allNamespaces} value={selectedNamespaces} onChange={(event) => setSelectedNamespaces(readMultiSelect(event))}>
                {namespaces.slice(0, 100).map((namespace) => (
                  <option key={namespace} value={namespace}>
                    {namespace}
                  </option>
                ))}
              </select>
              {!namespaces.length && <div style={styles.helperText}>No namespace values discovered. Leave all namespaces enabled or adjust the namespace label.</div>}
            </Field>
          </div>

          <div style={panelStyle('#3fcf8e')}>
            <h3 style={sectionTitleStyle}>2. Monitoring Categories</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10 }}>
              {monitorCategories.map((item, index) => (
                <button key={item.id} type="button" onClick={() => toggleCategory(item.id)} style={{ border: `1px solid ${selectedCategories.includes(item.id) ? 'rgba(63, 207, 142, 0.65)' : 'rgba(204, 204, 220, 0.18)'}`, borderRadius: 8, padding: 12, background: selectedCategories.includes(item.id) ? 'rgba(63, 207, 142, 0.1)' : 'rgba(204, 204, 220, 0.04)', color: 'inherit', textAlign: 'left', cursor: 'pointer' }}>
                  <div style={{ ...styles.rowBetween, gap: 8 }}>
                    <strong>{item.title}</strong>
                    {selectedCategories.includes(item.id) && <span style={{ color: '#3fcf8e' }}>✓</span>}
                  </div>
                  <div style={styles.helperText}>{item.detail}</div>
                </button>
              ))}
            </div>
            {!selectedCategories.length && <div style={{ ...styles.alert, marginTop: 12 }}>Select at least one monitoring category to preview a plan.</div>}
            {selectedCategories.includes('custom') && (
              <div style={{ ...styles.stack, marginTop: 14 }}>
                <Field label="Explicit metric names comma-separated">
                  <input style={styles.input} value={customExplicitMetrics} onChange={(event) => setCustomExplicitMetrics(event.target.value)} placeholder="http_requests_total,node_cpu_seconds_total" />
                </Field>
                <Field label="Include patterns comma-separated">
                  <input style={styles.input} value={customIncludePatterns} onChange={(event) => setCustomIncludePatterns(event.target.value)} placeholder=".*latency.*,custom_metric_.*" />
                </Field>
                <Field label="Exclude patterns comma-separated">
                  <input style={styles.input} value={customExcludePatterns} onChange={(event) => setCustomExcludePatterns(event.target.value)} />
                </Field>
              </div>
            )}
          </div>

          <div style={panelStyle('#5794f2')}>
            <h3 style={sectionTitleStyle}>3. Execution Limits</h3>
            <Field label="Mode">
              <select style={styles.input} value={scheduleMode} onChange={(event) => setScheduleMode(event.target.value as 'run_once' | 'scheduled')}>
                <option value="run_once">One-time</option>
                <option value="scheduled">Scheduled</option>
              </select>
            </Field>
            {scheduleMode === 'scheduled' ? (
              <Field label="Run every">
                <select style={styles.input} value={scheduleMinutes} onChange={(event) => setScheduleMinutes(Number(event.target.value))}>
                  <option value={5}>5m</option>
                  <option value={15}>15m</option>
                  <option value={30}>30m</option>
                  <option value={60}>1h</option>
                  <option value={360}>6h</option>
                </select>
              </Field>
            ) : null}
            <Field label="Analysis window">
              <select style={styles.input} value={analysisWindow} onChange={(event) => setAnalysisWindow(event.target.value)}>
                <option value="30m">30m</option>
                <option value="1h">1h</option>
                <option value="6h">6h</option>
                <option value="24h">24h</option>
                <option value="7d">7d</option>
              </select>
            </Field>
            <Field label="Query resolution">
              <select style={styles.input} value={executionInterval} onChange={(event) => setExecutionInterval(event.target.value)}>
                <option value="30s">30s</option>
                <option value="1m">1m</option>
                <option value="5m">5m</option>
                <option value="10m">10m</option>
              </select>
            </Field>
            <Field label="Max metrics per run">
              <input style={styles.input} type="number" value={maxMetricsPerRun} min={1} max={5000} onChange={(event) => setMaxMetricsPerRun(event.target.value)} />
            </Field>
            <Field label="Max parallel jobs">
              <input style={styles.input} type="number" value={maxParallelJobs} min={1} max={200} onChange={(event) => setMaxParallelJobs(event.target.value)} />
              <div style={{ ...styles.helperText, marginTop: 4 }}>
                Execution runs sequentially; this setting is reserved for future worker concurrency.
              </div>
            </Field>
          </div>
        </div>

        {scheduleError ? <div style={{ ...styles.alert, marginTop: 12 }}>{scheduleError}</div> : null}
        <div style={{ marginTop: 16, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button type="button" style={canPreview && !isPreviewing ? styles.button : { ...styles.button, ...styles.buttonDisabled }} disabled={!canPreview || isPreviewing} onClick={onPreview}>
            {isPreviewing ? 'Building preview...' : 'Preview metric plan'}
          </button>
          <button
            type="button"
            style={selectedCategories.length && !isSavingSchedule ? { ...styles.button, background: '#3fcf8e', color: '#08130e' } : { ...styles.button, ...styles.buttonDisabled }}
            disabled={!selectedCategories.length || isSavingSchedule}
            onClick={handleSaveSchedule}
          >
            {isSavingSchedule ? 'Saving...' : scheduleMode === 'scheduled' ? 'Save & Schedule' : 'Save'}
          </button>
        </div>
        <div style={styles.helperText}>Preview first, then run the planned jobs once, or save a schedule so it runs automatically without you.</div>
        </>
        )}
      </Card>
      ) : null}

      {uiStage === 'preview_loading' ? <PreviewLoadingPanel /> : null}
      {uiStage === 'preview_error' ? <PreviewErrorPanel onRetry={onPreview} onBack={handleBackToConfigure} /> : null}
      {uiStage === 'preview_ready' ? (
        <PreviewPlanPanel
          result={previewResult}
          rows={previewRows}
          canRunOnce={canRunOnce}
          isRunningOnce={isRunningOnce}
          onRunOnce={onRunOnce}
          onBack={handleBackToConfigure}
          statusFilter={previewStatusFilter}
          setStatusFilter={setPreviewStatusFilter}
          categoryFilter={previewCategoryFilter}
          setCategoryFilter={setPreviewCategoryFilter}
          conceptFilter={previewConceptFilter}
          setConceptFilter={setPreviewConceptFilter}
          expandedMetric={expandedPreviewMetric}
          setExpandedMetric={setExpandedPreviewMetric}
        />
      ) : null}
      {uiStage === 'running' ? <AutonomousRunningPanel plannedJobs={previewResult?.planned_jobs ?? runResult?.planned_jobs ?? null} /> : null}
      {uiStage === 'run_error' ? <RunErrorPanel result={runResult} onRetry={onRunOnce} onBack={handleBackToConfigure} /> : null}
      {runResult && ['overview_loading', 'overview_ready', 'overview_empty'].includes(uiStage) ? <AutonomousRunPanel result={runResult} /> : null}

      {['overview_loading', 'overview_ready', 'overview_empty', 'overview_error'].includes(uiStage) ? (
        <GrafanaAutonomousOverview
          backendUrl={backendUrl}
          data={dashboardData}
          findings={findings}
          state={dashboardState}
          endpointErrors={endpointErrors}
          onRetry={onRetryOverview}
          investigationFinding={investigationFinding}
          investigationMode={investigationMode}
          caseResult={caseResult}
          caseDetails={caseDetails}
          caseError={caseError}
          isCreatingCase={isCreatingCase}
          askState={askState}
          findingsLookupState={findingsLookupState}
          onOpenInvestigation={onOpenInvestigation}
          onInvestigateInteractive={onInvestigateInteractive}
          onCloseInvestigation={onCloseInvestigation}
          onCreateCase={onCreateCase}
          onEnableCategory={(category) => {
            if (!selectedCategories.includes(category)) toggleCategory(category);
            handleBackToConfigure();
          }}
          onPreviewNow={activePolicy ? () => onPreviewPolicy(activePolicy) : undefined}
          isPreviewingNow={isPreviewingPolicy}
          previewNowError={previewPolicyError}
          context={{
            sourceLabel: selectedPrometheusUid ? `Prometheus / ${selectedPrometheusUid}` : 'Prometheus / Grafana datasource',
            datasource: selectedPrometheusUid || 'Prometheus',
            policy: selectedCategories.length ? selectedCategories.map(humanize).join(', ') : 'Current monitoring policy',
            timeWindow: analysisWindow,
            environment,
          }}
        />
      ) : null}
    </div>
  );
}

function Kpi({ label, value, tone = '#d8d9da' }: { label: string; value: number; tone?: string }) {
  return (
    <div style={{ border: '1px solid rgba(204, 204, 220, 0.16)', borderRadius: 8, padding: 14, background: 'rgba(17, 18, 23, 0.55)' }}>
      <div style={{ color: tone, fontSize: 26, fontWeight: 900 }}>{value.toLocaleString()}</div>
      <div style={{ ...styles.helperText, marginTop: 2 }}>{label}</div>
    </div>
  );
}

function DashboardKpi({ label, value, detail, tone = '#d8d9da' }: { label: string; value: number | null; detail: string; tone?: string }) {
  return (
    <div style={{ border: '1px solid rgba(204, 204, 220, 0.16)', borderRadius: 8, padding: 14, background: 'rgba(17, 18, 23, 0.55)' }}>
      <div style={{ color: tone, fontSize: 24, fontWeight: 900 }}>{value === null ? '—' : value.toLocaleString()}</div>
      <div style={{ fontWeight: 800, marginTop: 6 }}>{label}</div>
      <div style={styles.helperText}>{detail}</div>
    </div>
  );
}

function GrafanaAutonomousOverview({
  backendUrl,
  data,
  findings,
  state,
  context,
  endpointErrors,
  onRetry,
  investigationFinding,
  investigationMode,
  caseResult,
  caseDetails,
  caseError,
  isCreatingCase,
  askState,
  findingsLookupState,
  onOpenInvestigation,
  onInvestigateInteractive,
  onCloseInvestigation,
  onCreateCase,
  onEnableCategory,
  onPreviewNow,
  isPreviewingNow,
  previewNowError,
}: {
  backendUrl: string;
  data: AutonomousDashboardData;
  findings: Finding[];
  state: 'loading' | 'error' | 'ready';
  context: {
    sourceLabel?: string | null;
    datasource?: string | null;
    policy?: string | null;
    timeWindow?: string | null;
    environment?: string | null;
  };
  endpointErrors: OverviewEndpointError[];
  onRetry: () => void;
  investigationFinding: Finding | null;
  investigationMode: 'investigate' | 'evidence';
  caseResult: GrafanaCaseCreateResponse | null;
  caseDetails: GrafanaCase | null;
  caseError: string;
  isCreatingCase: boolean;
  askState: AutonomousAskState;
  findingsLookupState: AutonomousFindingsLookupState;
  onOpenInvestigation: (finding: Finding, mode: 'investigate' | 'evidence') => void;
  onInvestigateInteractive: (finding: Finding) => void;
  onCloseInvestigation: () => void;
  onCreateCase: (finding: Finding) => Promise<void>;
  onEnableCategory?: (category: MonitoringCategory) => void;
  onPreviewNow?: () => void;
  isPreviewingNow?: boolean;
  previewNowError?: string;
}) {
  if (state === 'loading') {
    return (
      <Card>
        <div style={styles.emptyHero}>
          <div>
            <h2 style={{ margin: 0 }}>Loading autonomous monitoring overview...</h2>
            <p style={styles.muted}>Refreshing run metadata, findings, behavior summaries, history, and cases.</p>
          </div>
        </div>
      </Card>
    );
  }

  if (state === 'error') {
    return (
      <Card>
        <div style={styles.emptyHero}>
          <div>
            <h2 style={{ margin: 0 }}>Autonomous monitoring summary could not be loaded.</h2>
            <p style={styles.muted}>Check the selected backend URL and retry.</p>
            {endpointErrors.length ? (
              <div style={{ ...styles.stack, textAlign: 'left', marginTop: 16 }}>
                {endpointErrors.map((item) => (
                  <div key={`${item.apiFunction}:${item.endpoint}`} style={panelStyle('#f2495c')}>
                    <strong>{item.component}</strong>
                    <div style={styles.helperText}>{item.apiFunction} → {item.endpoint}</div>
                    <div style={styles.helperText}>{item.url}</div>
                  </div>
                ))}
              </div>
            ) : null}
            <button type="button" style={{ ...styles.button, marginTop: 16 }} onClick={onRetry}>
              Retry
            </button>
          </div>
        </div>
      </Card>
    );
  }

  const servicePriorities = buildServicePriorities(data.topFindings);
  const primaryService = servicePriorities[0] ?? null;
  const topFinding = data.topFindings[0] ?? null;
  const topRawFinding = topFinding ? matchingFinding(findings, topFinding) : null;
  const hasFindings = data.topFindings.length > 0;
  const disabledActionStyle = {
    ...styles.buttonDisabled,
    border: '1px solid rgba(204, 204, 220, 0.14)',
    opacity: 0.72,
  };
  const headline = primaryService
    ? primaryService.symptoms.length > 1
      ? `Likely incident candidate: ${primaryService.service}`
      : `Important finding detected: ${primaryService.service}`
    : 'No important findings detected';
  const summaryText = primaryService
    ? primaryService.symptoms.length > 1
      ? `${primaryService.service} shows ${primaryService.symptoms.length} related symptoms across ${primaryService.metrics.length} metric${primaryService.metrics.length === 1 ? '' : 's'}. Primary concern: ${primaryService.metrics[0]} ${primaryService.symptoms[0].behavior.toLowerCase()}.`
      : `${primaryService.service} / ${primaryService.metrics[0]} shows ${primaryService.symptoms[0].behavior.toLowerCase()} in the selected window.`
    : `${formatNullableCount(data.summary.executed)} metric${data.summary.executed === 1 ? '' : 's'} executed with no current-run findings.`;
  const nextStep = primaryService
    ? primaryService.symptoms.length > 1
      ? `Investigate ${primaryService.service} as one incident candidate and attach the related symptoms to a single case.`
      : `Investigate ${primaryService.service} / ${primaryService.metrics[0]} and create a case if it affects service health.`
    : 'No immediate investigation is recommended from this run. Review skipped or failed jobs if coverage looks too narrow.';

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <div style={styles.rowBetween}>
        <div>
          <div style={{ ...styles.helperText, marginTop: 0 }}>Overview / Autonomous Monitoring</div>
          <h2 style={{ margin: '4px 0 0' }}>Autonomous Monitoring Overview</h2>
          <p style={{ ...styles.muted, margin: '5px 0 0' }}>Current run result with historical executions shown separately.</p>
        </div>
        <div style={{ ...styles.row, justifyContent: 'flex-end' }}>
          <span style={styles.chip}>Source: {context.sourceLabel || context.datasource || 'Prometheus'}</span>
          <span style={styles.chip}>Policy: {context.policy || 'Current monitoring policy'}</span>
          <span style={styles.chip}>Window: {context.timeWindow || '24h'}</span>
          {context.environment ? <span style={styles.chip}>Environment: {context.environment}</span> : null}
        </div>
      </div>

      <div style={panelStyle(hasFindings ? '#b877d9' : '#3fcf8e')}>
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(320px, 0.85fr)', gap: 18, alignItems: 'stretch' }}>
          <div style={{ display: 'grid', gap: 14 }}>
            <div style={styles.row}>
              <span style={{ display: 'grid', placeItems: 'center', width: 40, height: 40, borderRadius: 999, border: `1px solid ${hasFindings ? '#b877d9' : '#3fcf8e'}`, color: hasFindings ? '#b877d9' : '#3fcf8e', fontSize: 22 }}>△</span>
              <div>
                <h3 style={{ margin: 0 }}>{headline}</h3>
                <p style={{ ...styles.muted, margin: '6px 0 0' }}>{summaryText}</p>
              </div>
            </div>
            <div style={styles.row}>
              <span title="Importance combines analyzer confidence, severity, signal count, and observed change size. Higher values should be reviewed first." style={styles.chip}>Highest importance {topFinding ? topFinding.importance.toFixed(2) : '—'} <InfoTip /></span>
              <span title="Symptoms are analyzer findings such as baseline shifts, spikes, trends, or anomalies. They are observations, not root cause." style={styles.chip}>{data.summary.findingsGenerated} symptom{data.summary.findingsGenerated === 1 ? '' : 's'} <InfoTip /></span>
              <span title="Affected metrics are unique metrics involved in the current-run findings." style={styles.chip}>{primaryService?.metrics.length ?? 0} metric{primaryService?.metrics.length === 1 ? '' : 's'} affected <InfoTip /></span>
              <span title="First observed is taken from finding comparison data or creation time." style={styles.chip}>First observed {formatCompactDate(topFinding?.firstObserved)} <InfoTip /></span>
            </div>
            <div>
              <strong>Recommended next step</strong>
              <p style={{ ...styles.muted, margin: '6px 0 0' }}>{nextStep}</p>
            </div>
            <div style={styles.row}>
              <button
                type="button"
                style={{ ...styles.button, background: hasFindings ? '#b877d9' : 'rgba(204, 204, 220, 0.18)', ...(topRawFinding ? {} : disabledActionStyle) }}
                disabled={!topRawFinding}
                title={topRawFinding ? 'Open this service and metric in Interactive Analysis.' : 'No current-run finding is available to investigate.'}
                onClick={() => topRawFinding && onInvestigateInteractive(topRawFinding)}
              >
                Investigate
              </button>
              <button
                type="button"
                style={{ ...styles.button, background: 'rgba(204, 204, 220, 0.12)', border: '1px solid rgba(204, 204, 220, 0.22)', ...(topRawFinding ? {} : disabledActionStyle) }}
                disabled={!topRawFinding || isCreatingCase}
                title={topRawFinding ? 'Create an investigation case from this finding.' : 'A finding must exist before a case can be created.'}
                onClick={() => topRawFinding && onCreateCase(topRawFinding)}
              >
                {isCreatingCase ? 'Creating...' : 'Create service case'}
              </button>
              <button
                type="button"
                style={{ ...styles.button, background: 'rgba(204, 204, 220, 0.08)', border: '1px solid rgba(204, 204, 220, 0.18)', ...(topRawFinding ? {} : disabledActionStyle) }}
                disabled={!topRawFinding}
                title={topRawFinding ? 'Open finding summary and signal evidence references.' : 'No current-run evidence is available.'}
                onClick={() => topRawFinding && onOpenInvestigation(topRawFinding, 'evidence')}
              >
                View evidence
              </button>
            </div>
            {caseResult ? <p style={{ ...styles.helperText, color: '#3fcf8e', margin: 0 }}>Case #{caseResult.case_id} created from finding #{caseResult.finding_id}.</p> : null}
            {caseError ? <p style={{ ...styles.helperText, color: '#ff7381', margin: 0 }}>{caseError}</p> : null}
          </div>
          <div style={{ borderLeft: '1px solid rgba(204, 204, 220, 0.12)', paddingLeft: 18 }}>
            <h3 style={sectionTitleStyle}>Related Symptoms <InfoTip title="Related symptoms are current-run findings grouped under the highest-priority service." /></h3>
            {primaryService ? (
              <div style={styles.stack}>
                {primaryService.symptoms.slice(0, 3).map((finding, index) => (
                  <div key={`${finding.metric}:${finding.behavior}:${index}`} style={{ display: 'grid', gridTemplateColumns: '28px minmax(0, 1fr) 54px 92px', gap: 10, alignItems: 'center', borderBottom: '1px solid rgba(204, 204, 220, 0.1)', paddingBottom: 10 }}>
                    <span style={{ display: 'grid', placeItems: 'center', width: 24, height: 24, borderRadius: 999, background: index === 0 ? '#b877d9' : index === 1 ? '#5794f2' : '#3fcf8e', color: '#fff', fontWeight: 800 }}>{index + 1}</span>
                    <div>
                      <strong>{finding.metric}</strong>
                      <div style={styles.row}>
                        <BehaviorPill label={finding.behavior} />
                        <SymptomScopeChip finding={matchingFinding(findings, finding)} onOpen={(raw) => onOpenInvestigation(raw, 'evidence')} />
                        {finding.observedChange ? <span style={styles.helperText}>{finding.observedChange}</span> : null}
                      </div>
                    </div>
                    <strong style={{ color: index === 0 ? '#b877d9' : '#5794f2' }}>{finding.importance.toFixed(2)}</strong>
                    <MiniSparkline tone={index === 0 ? '#b877d9' : index === 1 ? '#5794f2' : '#3fcf8e'} />
                  </div>
                ))}
              </div>
            ) : <p style={styles.muted}>No symptoms were detected in this run.</p>}
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 12 }}>
        <GrafanaAutonomousAskPanel askState={askState} />
        <GrafanaFindingsLookupPanel lookupState={findingsLookupState} />
      </div>

      <CurrentRunSummaryPanel data={data} />

      {(servicePriorities.length > 1 || data.behaviorDistribution.length > 1) ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.35fr) minmax(320px, 0.65fr)', gap: 12 }}>
          {servicePriorities.length > 1 ? (
            <ServicePrioritiesPanel
              servicePriorities={servicePriorities}
              findings={findings}
              onInvestigateInteractive={onInvestigateInteractive}
            />
          ) : null}
          {data.behaviorDistribution.length > 1 ? (
            <ObservedChangesPanel data={data} />
          ) : null}
        </div>
      ) : null}

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(260px, 0.95fr) minmax(280px, 1fr) minmax(260px, 0.85fr)', gap: 12 }}>
        <CoverageDetailsPanel selection={data.selection} onEnableCategory={onEnableCategory} onPreviewNow={onPreviewNow} isPreviewingNow={isPreviewingNow} previewNowError={previewNowError} />
        <RunHistoryPanel rows={data.executionRows} />
        <CasesPanel data={data} backendUrl={backendUrl} onCasesChanged={onRetry} />
      </div>
      {investigationFinding ? (
        <AutonomousInvestigationPanel
          backendUrl={backendUrl}
          finding={investigationFinding}
          mode={investigationMode}
          caseResult={caseResult}
          caseDetails={caseDetails}
          caseError={caseError}
          isCreatingCase={isCreatingCase}
          onCreateCase={() => onCreateCase(investigationFinding)}
          onClose={onCloseInvestigation}
        />
      ) : null}
    </div>
  );
}

const autonomousSuggestedQuestions = [
  'Summarize this autonomous run',
  'What changed in this run?',
  'What should I investigate first?',
  'Which metrics were skipped?',
  'Which findings are new in the last 24h?',
];

function CurrentRunSummaryPanel({ data }: { data: AutonomousDashboardData }) {
  const summaryItems = [
    { label: 'executed', value: data.summary.executed, tone: '#5794f2', detail: 'metrics analyzed' },
    { label: 'skipped', value: data.summary.skipped, tone: '#ffb357', detail: 'policy / filters' },
    { label: 'finding', value: data.summary.findingsGenerated, tone: '#b877d9', detail: 'generated' },
    { label: 'cases', value: data.summary.casesOpen, tone: '#3fcf8e', detail: 'created / open' },
  ];
  return (
    <div style={panelStyle('#68707f')}>
      <h3 style={{ ...sectionTitleStyle, color: '#f5f7ff', fontSize: 16, textTransform: 'none' }}>Current Run Summary</h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 10 }}>
        {summaryItems.map((item) => (
          <div key={item.label} style={{ border: '1px solid rgba(204, 204, 220, 0.16)', borderRadius: 8, padding: 14, background: 'rgba(17, 18, 23, 0.55)' }}>
            <div style={{ color: item.tone, fontSize: 24, fontWeight: 900 }}>{item.value === null ? '—' : item.value.toLocaleString()}</div>
            <div style={{ fontWeight: 850, marginTop: 5 }}>{item.label}</div>
            <div style={styles.helperText}>{item.detail}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ServicePrioritiesPanel({
  servicePriorities,
  findings,
  onInvestigateInteractive,
}: {
  servicePriorities: ReturnType<typeof buildServicePriorities>;
  findings: Finding[];
  onInvestigateInteractive: (finding: Finding) => void;
}) {
  return (
    <div id="top-findings" style={panelStyle('#ffb357')}>
      <div style={styles.rowBetween}>
        <h3 style={sectionTitleStyle}>Service Priorities <InfoTip title="Services are ranked by their highest-importance current-run symptom. Multiple symptoms on one service are grouped to avoid creating duplicate incident candidates." /></h3>
        <span style={styles.helperText}>{servicePriorities.length} service{servicePriorities.length === 1 ? '' : 's'} shown</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.25fr 1fr 1fr 1fr', gap: '10px 14px', fontSize: 12, overflowX: 'auto', alignItems: 'center' }}>
        {['Service', 'Symptoms', 'Metrics affected', 'Highest importance', 'Recommended action'].map((header) => <div key={header} style={styles.tableHeader}>{header}</div>)}
        {servicePriorities.slice(0, 5).map((service, index) => (
          <React.Fragment key={service.service}>
            <div style={{ borderLeft: `4px solid ${index === 0 ? '#b877d9' : index === 1 ? '#5794f2' : '#3fcf8e'}`, paddingLeft: 10 }}>
              <strong>{service.service}</strong>
              <div style={styles.helperText}>{service.symptoms.length > 1 ? 'Likely incident candidate' : 'Single symptom'}</div>
            </div>
            <div style={styles.row}>{service.behaviors.slice(0, 3).map((behavior) => <BehaviorPill key={behavior} label={behavior} />)}</div>
            <div><strong>{service.metrics.length}</strong><div style={styles.helperText}>{service.metrics.slice(0, 3).join(', ')}</div></div>
            <ImportanceBar value={service.highestImportance} />
            <button
              type="button"
              style={styles.tableRowButton}
              onClick={() => {
                const finding = matchingFinding(findings, service.symptoms[0]);
                if (finding) onInvestigateInteractive(finding);
              }}
            >
              Investigate {service.service}
            </button>
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}

function ObservedChangesPanel({ data }: { data: AutonomousDashboardData }) {
  return (
    <div style={panelStyle('#ffb357')}>
      <h3 style={sectionTitleStyle}>Observed Changes <InfoTip title="Observed changes are analyzer-detected metric patterns, such as spikes or baseline shifts. They are not root cause." /></h3>
      <BehaviorDonut items={data.behaviorDistribution} total={data.summary.findingsGenerated} />
    </div>
  );
}

function CoverageDetailsPanel({ selection, onEnableCategory, onPreviewNow, isPreviewingNow, previewNowError }: { selection: AutonomousSelectionSummary; onEnableCategory?: (category: MonitoringCategory) => void; onPreviewNow?: () => void; isPreviewingNow?: boolean; previewNowError?: string }) {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <div style={panelStyle('#3fcf8e')}>
      <div style={styles.rowBetween}>
        <div>
          <h3 style={{ ...sectionTitleStyle, color: '#f5f7ff', fontSize: 16, textTransform: 'none' }}>Coverage Details <InfoTip title="Metrics discovered in this preview vs. how many your policy selected, with a breakdown of why the rest were excluded - so you know which monitoring categories to enable or disable." /></h3>
          <div style={{ ...styles.row, color: '#cfd3e6' }}>
            <span style={{ color: '#5794f2' }}>{formatNullableCount(selection.discovered)} discovered</span>
            <span>·</span>
            <span style={{ color: '#3fcf8e' }}>{formatNullableCount(selection.selected)} selected</span>
            <span>·</span>
            <span style={{ color: '#ffb357' }}>{formatNullableCount(selection.excluded)} excluded</span>
            <span>·</span>
            <span>{selection.reductionPercent === null ? '—' : `${selection.reductionPercent.toFixed(1)}%`} reduction</span>
          </div>
        </div>
        <button type="button" style={styles.button} onClick={() => setIsOpen((current) => !current)}>
          {isOpen ? 'Hide' : 'Show'}
        </button>
      </div>
      {isOpen ? <div style={{ marginTop: 14 }}><MetricSelectionFunnel selection={selection} onEnableCategory={onEnableCategory} onPreviewNow={onPreviewNow} isPreviewingNow={isPreviewingNow} previewNowError={previewNowError} /></div> : null}
    </div>
  );
}

function RunHistoryPanel({ rows }: { rows: AutonomousDashboardData['executionRows'] }) {
  return (
    <div style={panelStyle('#5794f2')}>
      <h3 style={{ ...sectionTitleStyle, color: '#f5f7ff', fontSize: 16, textTransform: 'none' }}>Run History <InfoTip title="Recent autonomous runs. Failures here may indicate overly broad scope or queries returning multiple series." /></h3>
      {rows.length ? (
        <div style={{ display: 'grid', gap: 8 }}>
          {rows.slice(0, 5).map((row) => (
            <div key={row.id} style={{ display: 'grid', gridTemplateColumns: '1.2fr 0.8fr 0.7fr', gap: 10, alignItems: 'center', borderBottom: '1px solid rgba(204, 204, 220, 0.1)', paddingBottom: 8 }}>
              <div>
                <strong>{row.current ? 'Current run' : row.scope}</strong>
                <div style={styles.helperText}>{row.current ? row.scope : row.metrics}</div>
                {row.errorSummary ? <div style={{ ...styles.helperText, color: '#ff7381' }}>{row.errorSummary}</div> : null}
              </div>
              <StatusBadge status={row.status} />
              <div>{formatCompactDate(row.completed)}</div>
            </div>
          ))}
        </div>
      ) : <p style={styles.muted}>No execution history returned yet.</p>}
    </div>
  );
}

/** Recent cases; clicking one opens it in the case workflow drawer (the same one Interactive
 * Analysis uses), so it can be investigated, resolved and published to memory without leaving
 * Grafana. The overview is refreshed on close when anything was saved, so statuses stay current. */
export function CasesPanel({ data, backendUrl, onCasesChanged }: { data: AutonomousDashboardData; backendUrl: string; onCasesChanged?: () => void }) {
  const [openCase, setOpenCase] = useState<GrafanaCase | null>(null);
  const [openingCaseId, setOpeningCaseId] = useState<number | null>(null);
  const [openError, setOpenError] = useState('');
  const [caseChanged, setCaseChanged] = useState(false);

  async function openCaseById(caseId: number) {
    setOpeningCaseId(caseId);
    setOpenError('');
    try {
      setOpenCase(await getCase(backendUrl, caseId));
      setCaseChanged(false);
    } catch {
      setOpenError(`Could not open case #${caseId}. Check the backend connection and retry.`);
    } finally {
      setOpeningCaseId(null);
    }
  }

  function closeCase() {
    setOpenCase(null);
    if (caseChanged) onCasesChanged?.();
  }

  return (
    <div style={panelStyle('#b877d9')}>
      <h3 style={{ ...sectionTitleStyle, color: '#f5f7ff', fontSize: 16, textTransform: 'none' }}>{data.casesScope === 'current_run' ? 'Cases Created From This Run' : 'Recent Cases from History'} <InfoTip title="Cases are investigation records. Current-run cases are linked to findings generated by this run." /></h3>
      {data.recentCases.length ? (
        <div style={styles.stack}>
          {data.recentCases.slice(0, 5).map((caseItem) => (
            <div key={caseItem.id} style={styles.rowBetween}>
              <div style={{ minWidth: 0 }}>
                <button
                  type="button"
                  style={{ ...styles.tableRowButton, fontWeight: 700 }}
                  disabled={openingCaseId !== null}
                  title="Open this case in the investigation workflow"
                  onClick={() => openCaseById(caseItem.id)}
                >
                  {caseItem.title}
                </button>
                <div style={styles.helperText}>{openingCaseId === caseItem.id ? 'Opening case...' : caseItem.status}</div>
              </div>
              <div style={styles.helperText}>{formatCompactDate(caseItem.updatedAt)}</div>
            </div>
          ))}
        </div>
      ) : <p style={styles.muted}>No cases were created for the current run.</p>}
      {openError ? <div style={{ ...styles.helperText, color: '#ff7381' }}>{openError}</div> : null}
      <InvestigationDrawer
        open={openCase !== null}
        caseResult={null}
        caseDetails={openCase}
        finding={null}
        backendUrl={backendUrl}
        onClose={closeCase}
        onCaseChange={(updated) => {
          setOpenCase(updated);
          setCaseChanged(true);
        }}
        onError={() => undefined}
      />
    </div>
  );
}

function CollapsibleInsightPanel({
  title,
  subtitle,
  tone,
  defaultOpen = false,
  children,
}: {
  title: string;
  subtitle: string;
  tone: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  return (
    <div style={panelStyle(tone)}>
      <button
        type="button"
        onClick={() => setIsOpen((current) => !current)}
        style={{
          width: '100%',
          border: 0,
          background: 'transparent',
          color: 'inherit',
          padding: 0,
          textAlign: 'left',
          cursor: 'pointer',
        }}
      >
        <div style={styles.rowBetween}>
          <div>
            <h3 style={{ ...sectionTitleStyle, color: '#f5f7ff', fontSize: 16, textTransform: 'none' }}>
              {title}
            </h3>
            <p style={{ ...styles.muted, margin: '4px 0 0', color: '#cfd3e6' }}>{subtitle}</p>
          </div>
          <span style={{ ...styles.chip, color: '#f5f7ff', borderColor: `${tone}88` }}>{isOpen ? 'Hide' : 'Show'} ▾</span>
        </div>
      </button>
      {isOpen ? <div style={{ marginTop: 14 }}>{children}</div> : null}
    </div>
  );
}

function GrafanaAutonomousAskPanel({ askState }: { askState: AutonomousAskState }) {
  const evidenceCount = (key: string) => {
    const value = askState.answer?.evidence?.[key];
    return Array.isArray(value) ? value.length : 0;
  };
  return (
    <CollapsibleInsightPanel
      title="Ask Ops Signals"
      subtitle="Grounded Q&A from this autonomous run, skipped jobs, findings, and cases."
      tone="#3fcf8e"
    >
      <p style={{ ...styles.muted, color: '#cfd3e6' }}>Answers are generated from stored autonomous evidence. No external LLM is required. <InfoTip title="Answers are generated from stored autonomous runs, jobs, findings, and cases. No external LLM is required." /></p>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {autonomousSuggestedQuestions.map((question) => (
          <button key={question} type="button" style={styles.questionButton} disabled={askState.isLoading} onClick={() => askState.ask(question)}>
            {question}
          </button>
        ))}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto', gap: 8, marginTop: 12 }}>
        <input
          style={styles.input}
          value={askState.question}
          onChange={(event) => askState.setQuestion(event.target.value)}
          placeholder="Ask: what changed in checkout in the last 24h?"
        />
        <button type="button" style={styles.button} disabled={askState.isLoading || !askState.question.trim()} onClick={() => askState.ask()}>
          {askState.isLoading ? 'Asking...' : 'Ask'}
        </button>
      </div>
      {askState.error ? <p style={{ ...styles.helperText, color: '#ff7381' }}>{askState.error}</p> : null}
      {askState.answer ? (
        <div style={{ ...panelStyle('#3fcf8e'), marginTop: 12, background: 'rgba(63, 207, 142, 0.06)' }}>
          <div style={styles.rowBetween}>
            <div>
              <strong>{askState.answer.headline}</strong>
              <div style={styles.helperText}>Priority {askState.answer.priority} · confidence {(askState.answer.confidence * 100).toFixed(0)}%</div>
            </div>
            <div style={{ ...styles.row, justifyContent: 'flex-end' }}>
              <span style={styles.chip}>{evidenceCount('finding_ids')} findings</span>
              <span style={styles.chip}>{evidenceCount('job_ids')} jobs</span>
              <span style={styles.chip}>{evidenceCount('case_ids')} cases</span>
            </div>
          </div>
          <p style={styles.muted}>{askState.answer.answer}</p>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {askState.answer.key_points.map((point) => <li key={point}>{point}</li>)}
          </ul>
        </div>
      ) : null}
    </CollapsibleInsightPanel>
  );
}

function GrafanaFindingsLookupPanel({ lookupState }: { lookupState: AutonomousFindingsLookupState }) {
  return (
    <CollapsibleInsightPanel
      title="Find Recent Findings"
      subtitle="Search persisted finding rows by time, service, metric, or text."
      tone="#5794f2"
    >
      <p style={{ ...styles.muted, color: '#cfd3e6' }}>Use this to show what was stored automatically and ask follow-up questions from finding evidence. <InfoTip title="Searches persisted finding rows by time window, service, metric, and text." /></p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 8 }}>
        <Field label="Window">
          <select style={styles.input} value={lookupState.window} onChange={(event) => lookupState.setWindow(event.target.value as FindingsWindow)}>
            <option value="1h">Last 1 hour</option>
            <option value="6h">Last 6 hours</option>
            <option value="24h">Last 24 hours</option>
            <option value="7d">Last 7 days</option>
          </select>
        </Field>
        <Field label="Search text">
          <input style={styles.input} value={lookupState.query} onChange={(event) => lookupState.setQuery(event.target.value)} placeholder="baseline, spike" />
        </Field>
        <Field label="Service">
          <input style={styles.input} value={lookupState.service} onChange={(event) => lookupState.setService(event.target.value)} placeholder="optional" />
        </Field>
        <Field label="Metric">
          <input style={styles.input} value={lookupState.metricName} onChange={(event) => lookupState.setMetricName(event.target.value)} placeholder="optional" />
        </Field>
      </div>
      <button type="button" style={{ ...styles.button, marginTop: 10 }} disabled={lookupState.isLoading} onClick={lookupState.search}>
        {lookupState.isLoading ? 'Searching...' : 'Find recent findings'}
      </button>
      {lookupState.error ? <p style={{ ...styles.helperText, color: '#ff7381' }}>{lookupState.error}</p> : null}
      <div style={{ ...styles.stack, marginTop: 12 }}>
        {lookupState.findings.length ? lookupState.findings.map((finding) => (
          <div key={finding.id} style={styles.rowBetween}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <strong>{finding.service} / {finding.metric_name}</strong>
              <div style={styles.helperText}>{finding.title}</div>
              <div style={styles.helperText}>Importance {finding.importance_score.toFixed(2)} · {humanize(finding.category)} · {formatCompactDate(finding.created_at)}</div>
              <PluginBreakdownDisclosure finding={finding} />
            </div>
            <button type="button" style={{ ...styles.tableRowButton, alignSelf: 'flex-start' }} onClick={() => lookupState.askAboutFinding(finding)}>Ask</button>
          </div>
        )) : <p style={styles.muted}>No findings matched the selected filters.</p>}
      </div>
    </CollapsibleInsightPanel>
  );
}

function SymptomScopeChip({ finding, onOpen }: { finding: Finding | null; onOpen: (finding: Finding) => void }) {
  if (!finding) return null;
  return <PluginScopeChip finding={finding} onClick={() => onOpen(finding)} />;
}

function matchingFinding(findings: Finding[], row: AutonomousDashboardData['topFindings'][number] | null | undefined) {
  if (!row) return null;
  if (row.id) {
    const byId = findings.find((finding) => finding.id === row.id);
    if (byId) return byId;
  }
  return findings.find((finding) => (
    finding.service === row.service &&
    finding.metric_name === row.metric &&
    Math.abs((finding.importance_score ?? 0) - row.importance) < 0.0001
  )) ?? null;
}

function AutonomousInvestigationPanel({
  backendUrl,
  finding,
  mode,
  caseResult,
  caseDetails,
  caseError,
  isCreatingCase,
  onCreateCase,
  onClose,
}: {
  backendUrl: string;
  finding: Finding;
  mode: 'investigate' | 'evidence';
  caseResult: GrafanaCaseCreateResponse | null;
  caseDetails: GrafanaCase | null;
  caseError: string;
  isCreatingCase: boolean;
  onCreateCase: () => void;
  onClose: () => void;
}) {
  const breakdown = findingBreakdown(finding);
  // The breakdown has its own section; the raw comparison view shows the rest.
  const { breakdown: _breakdown, ...comparison } = finding.comparison_json ?? {};
  const comparisonEntries = Object.entries(comparison).filter(([, value]) => value !== null && value !== undefined);
  const activeCaseId = caseDetails?.id ?? caseResult?.case_id;
  const [ticket, setTicket] = useState<CaseTicketLink | null>(null);
  const [isTicketLoading, setIsTicketLoading] = useState(false);
  const [ticketOperation, setTicketOperation] = useState<CaseTicketOperation | null>(null);
  const [ticketError, setTicketError] = useState('');

  useEffect(() => {
    if (!activeCaseId || !backendUrl) {
      setTicket(null);
      setTicketOperation(null);
      setTicketError('');
      return;
    }
    let isMounted = true;
    setIsTicketLoading(true);
    getCaseTicket(backendUrl, activeCaseId)
      .then((link) => {
        if (isMounted) setTicket(link);
      })
      .catch(() => {
        if (isMounted) setTicket(null);
      })
      .finally(() => {
        if (isMounted) setIsTicketLoading(false);
      });
    return () => {
      isMounted = false;
    };
  }, [activeCaseId, backendUrl]);

  const handleCreateTicket = async () => {
    if (!activeCaseId || !backendUrl) return;
    setIsTicketLoading(true);
    setTicketError('');
    try {
      const op = await createCaseTicket(backendUrl, activeCaseId, 'jira');
      setTicketOperation(op);
      if (op.status === 'completed') {
        const link = await getCaseTicket(backendUrl, activeCaseId);
        setTicket(link);
      }
    } catch (err: any) {
      setTicketError(err?.message || 'Failed to queue Jira ticket creation');
    } finally {
      setIsTicketLoading(false);
    }
  };

  const handleSyncTicket = async () => {
    if (!activeCaseId || !backendUrl) return;
    setIsTicketLoading(true);
    setTicketError('');
    try {
      const op = await syncCaseTicket(backendUrl, activeCaseId, 'jira');
      setTicketOperation(op);
      const link = await getCaseTicket(backendUrl, activeCaseId);
      setTicket(link);
    } catch (err: any) {
      setTicketError(err?.message || 'Failed to sync Jira ticket');
    } finally {
      setIsTicketLoading(false);
    }
  };
  return (
    <div id="autonomous-investigation" style={panelStyle(mode === 'evidence' ? '#5794f2' : '#b877d9')}>
      <div style={styles.rowBetween}>
        <div>
          <div style={styles.helperText}>{mode === 'evidence' ? 'Evidence' : 'Investigation'} / Current Finding</div>
          <h3 style={{ margin: '4px 0 0' }}>{finding.title}</h3>
          <p style={{ ...styles.muted, margin: '6px 0 0' }}>{finding.summary}</p>
        </div>
        <button type="button" style={{ ...styles.button, background: 'rgba(204, 204, 220, 0.08)' }} onClick={onClose}>Close</button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(240px, 0.75fr) minmax(280px, 1fr)', gap: 12, marginTop: 14 }}>
        <div style={{ ...styles.stack, border: '1px solid rgba(204, 204, 220, 0.12)', borderRadius: 8, padding: 14 }}>
          <div style={styles.row}><SeverityPill severity={finding.health_status} /><BehaviorPill label={humanize(finding.category)} /></div>
          <div style={styles.detailGrid}>
            <div><div style={styles.helperText}>Service</div><strong>{finding.service || 'unknown'}</strong></div>
            <div><div style={styles.helperText}>Metric</div><strong>{finding.metric_name}</strong></div>
            <div><div style={styles.helperText}>Importance</div><strong>{finding.importance_score.toFixed(2)}</strong></div>
            <div><div style={styles.helperText}>Analysis run</div><strong>{finding.analysis_run_id || 'unknown'}</strong></div>
          </div>
          <button
            type="button"
            style={{ ...styles.button, width: 'fit-content', ...(finding.id ? {} : styles.buttonDisabled) }}
            disabled={isCreatingCase || !finding.id}
            onClick={onCreateCase}
            title={finding.id ? 'Create a case using the existing finding-case workflow.' : 'This finding has not been persisted yet.'}
          >
            {isCreatingCase ? 'Creating case...' : 'Create Case'}
          </button>
          {caseResult ? <div style={{ ...styles.helperText, color: '#3fcf8e' }}>Case #{caseResult.case_id} created from finding #{caseResult.finding_id}.</div> : null}
          {caseError ? <div style={{ ...styles.helperText, color: '#ff7381' }}>{caseError}</div> : null}
          {caseDetails ? (
            <div style={{ borderTop: '1px solid rgba(204, 204, 220, 0.12)', paddingTop: 10 }}>
              <div style={styles.helperText}>Case workflow</div>
              <strong>{caseDetails.case_title}</strong>
              <div style={styles.row}>
                <StatusBadge status={caseDetails.case_status} />
                <StatusBadge status={caseDetails.investigation_status} />
              </div>
              <p style={{ ...styles.muted, margin: '6px 0 0' }}>Continue investigation, RCA, resolution, and knowledge publishing in the existing case flow.</p>
            </div>
          ) : null}
          {activeCaseId ? (
            <div style={{ borderTop: '1px solid rgba(204, 204, 220, 0.12)', paddingTop: 10, marginTop: 10 }}>
              <div style={styles.helperText}>External Ticketing</div>
              {ticket ? (
                <div style={{ ...styles.stack, marginTop: 4, gap: 6 }}>
                  <div style={styles.row}>
                    <span style={{ ...styles.chip, background: '#0052cc', color: '#fff', fontWeight: 600 }}>Jira</span>
                    <a
                      href={ticket.ticket_url}
                      target="_blank"
                      rel="noreferrer"
                      style={{ color: '#5794f2', fontWeight: 700, textDecoration: 'underline' }}
                    >
                      {ticket.display_key}
                    </a>
                    <span style={styles.chip}>{ticket.observed_remote_status || 'Linked'}</span>
                  </div>
                  <div style={styles.row}>
                    <button
                      type="button"
                      style={{ ...styles.button, padding: '4px 10px', fontSize: 12, background: 'rgba(204, 204, 220, 0.08)' }}
                      disabled={isTicketLoading}
                      onClick={handleSyncTicket}
                    >
                      {isTicketLoading ? 'Syncing...' : 'Sync Ticket'}
                    </button>
                    {ticket.last_synced_at ? (
                      <span style={{ ...styles.helperText, margin: 0 }}>
                        Synced {new Date(ticket.last_synced_at).toLocaleTimeString()}
                      </span>
                    ) : null}
                  </div>
                </div>
              ) : ticketOperation && (ticketOperation.status === 'pending' || ticketOperation.status === 'processing') ? (
                <div style={{ ...styles.helperText, color: '#e5a000', marginTop: 4 }}>
                  Ticket operation {ticketOperation.operation_type} is {ticketOperation.status}...
                </div>
              ) : ticketOperation && ticketOperation.status === 'ambiguous_outcome' ? (
                <div style={{ ...styles.helperText, color: '#ff7381', marginTop: 4 }}>
                  Ticket creation ambiguous: check Jira before retrying. Resolve in Standalone App Case Details.
                </div>
              ) : (
                <div style={{ marginTop: 6 }}>
                  <button
                    type="button"
                    style={{ ...styles.button, background: '#0052cc', color: '#fff', fontSize: 12, padding: '4px 12px' }}
                    disabled={isTicketLoading}
                    onClick={handleCreateTicket}
                    title="Create Jira issue for this case"
                  >
                    {isTicketLoading ? 'Queueing...' : 'Create Jira Ticket'}
                  </button>
                </div>
              )}
              {ticketError ? <div style={{ ...styles.helperText, color: '#ff7381', marginTop: 4 }}>{ticketError}</div> : null}
            </div>
          ) : null}
        </div>

        <div style={{ ...styles.stack, border: '1px solid rgba(204, 204, 220, 0.12)', borderRadius: 8, padding: 14 }}>
          <h3 style={sectionTitleStyle}>Evidence Snapshot <InfoTip title="Autonomous evidence uses persisted finding fields. Open Interactive Analysis when you need the full metric timeline for a single metric." /></h3>
          <div>
            <div style={styles.helperText}>Signal ids supporting this finding</div>
            {finding.signal_ids.length ? (
              <div style={styles.row}>{finding.signal_ids.map((id) => <span key={id} style={styles.chip}>{id}</span>)}</div>
            ) : <p style={styles.muted}>No signal ids were attached to this finding.</p>}
          </div>
          {comparisonEntries.length ? (
            <div>
              <div style={styles.helperText}>Comparison data</div>
              <pre style={{ margin: '6px 0 0', whiteSpace: 'pre-wrap', border: '1px solid rgba(204, 204, 220, 0.12)', borderRadius: 8, padding: 12, overflow: 'auto', maxHeight: 220 }}>
                {JSON.stringify(comparison, null, 2)}
              </pre>
            </div>
          ) : <p style={styles.muted}>No comparison details were returned for this finding.</p>}
        </div>
      </div>
      {breakdown ? <div style={{ marginTop: 12 }}><PluginBreakdownSection breakdown={breakdown} /></div> : null}
      <div style={{ marginTop: 12 }}><PluginSeenBefore backendUrl={backendUrl} findingId={finding.id} service={finding.service} /></div>
    </div>
  );
}

function ImportanceBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, value * 100));
  const tone = value >= 0.85 ? '#f2495c' : value >= 0.65 ? '#ffb357' : '#5794f2';
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '42px minmax(48px, 1fr)', gap: 8, alignItems: 'center' }}>
      <strong style={{ color: tone }}>{value.toFixed(2)}</strong>
      <span style={{ height: 5, borderRadius: 999, background: 'rgba(204, 204, 220, 0.12)', overflow: 'hidden' }}>
        <span style={{ display: 'block', width: `${pct}%`, height: '100%', borderRadius: 999, background: tone }} />
      </span>
    </div>
  );
}

function InfoTip({ title = 'More information' }: { title?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      tabIndex={0}
      style={{ position: 'relative', display: 'inline-grid', placeItems: 'center', width: 16, height: 16, borderRadius: 999, border: '1px solid rgba(204, 204, 220, 0.35)', color: 'rgba(204, 204, 220, 0.76)', fontSize: 11, marginLeft: 5, cursor: 'help', outline: 'none' }}
    >
      i
      {open ? (
        <span style={{ position: 'absolute', zIndex: 20, bottom: 'calc(100% + 8px)', left: '50%', transform: 'translateX(-50%)', width: 260, padding: '9px 10px', border: '1px solid rgba(204, 204, 220, 0.24)', borderRadius: 6, background: '#111217', color: 'rgba(242, 244, 248, 0.94)', boxShadow: '0 12px 32px rgba(0, 0, 0, 0.38)', lineHeight: 1.35, fontSize: 12, fontWeight: 500, textAlign: 'left', pointerEvents: 'none' }}>
          {title}
        </span>
      ) : null}
    </span>
  );
}

function MiniSparkline({ tone }: { tone: string }) {
  return (
    <svg viewBox="0 0 90 32" width="90" height="32" aria-hidden="true">
      <polyline points="2,24 10,22 18,25 26,18 34,19 42,15 50,17 58,11 66,13 74,8 88,12" fill="none" stroke={tone} strokeWidth="2" />
      <line x1="74" y1="4" x2="74" y2="29" stroke="rgba(204, 204, 220, 0.35)" strokeDasharray="2 2" />
    </svg>
  );
}

function buildServicePriorities(findings: AutonomousDashboardData['topFindings']) {
  const grouped = findings.reduce<Record<string, {
    service: string;
    symptoms: typeof findings;
    metrics: string[];
    behaviors: string[];
    highestImportance: number;
    href: string;
  }>>((acc, finding) => {
    const item = acc[finding.service] ?? {
      service: finding.service,
      symptoms: [],
      metrics: [],
      behaviors: [],
      highestImportance: 0,
      href: finding.href,
    };
    item.symptoms.push(finding);
    item.metrics = Array.from(new Set([...item.metrics, finding.metric]));
    item.behaviors = Array.from(new Set([...item.behaviors, finding.behavior]));
    if (finding.importance > item.highestImportance) {
      item.highestImportance = finding.importance;
      item.href = finding.href;
    }
    acc[finding.service] = item;
    return acc;
  }, {});

  return Object.values(grouped).sort((a, b) => b.highestImportance - a.highestImportance);
}

function BehaviorPill({ label }: { label: string }) {
  const tone = label.toLowerCase().includes('trend') ? '#ffb357' : label.toLowerCase().includes('spike') ? '#f2495c' : '#5794f2';
  return <span style={{ ...styles.chip, width: 'fit-content', color: tone, borderColor: `${tone}66` }}>{label}</span>;
}

function SeverityPill({ severity }: { severity: string }) {
  // A finding's level: "normal" is low importance, not healthy, so it is grey rather than green.
  const level = findingLevel(severity);
  const tone = level.chip === 'error' ? '#f2495c' : level.chip === 'warning' ? '#ffb357' : '#8a95a5';
  return <span style={{ ...styles.chip, width: 'fit-content', color: tone, borderColor: `${tone}66` }}>{level.label}</span>;
}

function BehaviorDonut({ items, total }: { items: Array<{ label: string; count: number }>; total: number }) {
  const palette = ['#5794f2', '#ffb357', '#3fcf8e', '#b877d9', '#33a2a2', '#f2cc0c', '#8a95a5'];
  const safeTotal = total || items.reduce((sum, item) => sum + item.count, 0) || 1;
  let offset = 0;
  const segments = items.map((item, index) => {
    const length = (item.count / safeTotal) * 100;
    const segment = { ...item, color: palette[index % palette.length], dash: `${length} ${100 - length}`, offset: -offset };
    offset += length;
    return segment;
  });

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '130px minmax(0, 1fr)', gap: 18, alignItems: 'center' }}>
      <div style={{ position: 'relative', width: 124, height: 124 }}>
        <svg viewBox="0 0 42 42" width="124" height="124" aria-label="Behavior distribution chart">
          <circle cx="21" cy="21" r="15.9" fill="transparent" stroke="rgba(204, 204, 220, 0.14)" strokeWidth="7" />
          {segments.map((segment) => (
            <circle key={segment.label} cx="21" cy="21" r="15.9" fill="transparent" stroke={segment.color} strokeWidth="7" strokeDasharray={segment.dash} strokeDashoffset={segment.offset} transform="rotate(-90 21 21)" />
          ))}
        </svg>
        <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', textAlign: 'center' }}>
          <div><div style={{ fontSize: 24, fontWeight: 900 }}>{safeTotal}</div><div style={styles.helperText}>Total</div></div>
        </div>
      </div>
      <div style={styles.stack}>
        {segments.map((item) => (
          <div key={item.label} style={styles.rowBetween}>
            <span style={{ ...styles.row, gap: 8 }}><span style={{ width: 9, height: 9, borderRadius: 999, background: item.color }} />{item.label}</span>
            <strong>{item.count} ({Math.round((item.count / safeTotal) * 100)}%)</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function MetricSelectionFunnel({ selection, onEnableCategory, onPreviewNow, isPreviewingNow, previewNowError }: { selection: AutonomousSelectionSummary; onEnableCategory?: (category: MonitoringCategory) => void; onPreviewNow?: () => void; isPreviewingNow?: boolean; previewNowError?: string }) {
  const discovered = selection.discovered ?? 0;
  const selected = selection.selected ?? 0;
  const excluded = selection.excluded ?? Math.max(discovered - selected, 0);
  return (
    <div style={styles.stack}>
      <div style={{ display: 'grid', gridTemplateColumns: '150px minmax(0, 1fr)', gap: 16, alignItems: 'center' }}>
        <svg viewBox="0 0 160 170" width="150" height="160" aria-label="Metric selection funnel">
          <polygon points="10,10 150,10 130,62 30,62" fill="#3fcf8e" opacity="0.85" />
          <polygon points="30,62 130,62 108,112 52,112" fill="#73bf69" opacity="0.9" />
          <polygon points="52,112 108,112 80,160" fill="#ff9830" opacity="0.92" />
          <text x="80" y="37" textAnchor="middle" fill="#fff" fontSize="20" fontWeight="800">{formatNullableCount(discovered)}</text>
          <text x="80" y="88" textAnchor="middle" fill="#fff" fontSize="18" fontWeight="800">{formatNullableCount(selected)}</text>
          <text x="80" y="135" textAnchor="middle" fill="#fff" fontSize="17" fontWeight="800">{formatNullableCount(excluded)}</text>
        </svg>
        <div style={styles.stack}>
          <div style={styles.rowBetween}><span>Discovered</span><strong>{formatNullableCount(selection.discovered)}</strong></div>
          <div style={styles.rowBetween}><span>Selected</span><strong>{formatNullableCount(selection.selected)}</strong></div>
          <div style={styles.rowBetween}><span>Excluded</span><strong>{formatNullableCount(selection.excluded)}</strong></div>
          <div style={styles.infoNote}>{selection.selectedLabel}</div>
          {selection.reductionPercent !== null ? <div style={{ textAlign: 'center', marginTop: 8 }}><div style={{ color: '#3fcf8e', fontSize: 24, fontWeight: 900 }}>{selection.reductionPercent.toFixed(1)}%</div><div style={styles.helperText}>Reduction</div></div> : null}
        </div>
      </div>
      <ExclusionReasonBreakdown selection={selection} onEnableCategory={onEnableCategory} onPreviewNow={onPreviewNow} isPreviewingNow={isPreviewingNow} previewNowError={previewNowError} />
    </div>
  );
}

function ExclusionReasonBreakdown({ selection, onEnableCategory, onPreviewNow, isPreviewingNow, previewNowError }: { selection: AutonomousSelectionSummary; onEnableCategory?: (category: MonitoringCategory) => void; onPreviewNow?: () => void; isPreviewingNow?: boolean; previewNowError?: string }) {
  const [expandedReason, setExpandedReason] = useState<string | null>(null);
  if (!selection.reasonsAvailable) {
    return (
      <div style={styles.stack}>
        <div style={{ ...styles.row, alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
          <div style={styles.helperText}>Run a preview to see why each discovered metric was or wasn't selected.</div>
          {onPreviewNow ? (
            <button type="button" style={styles.button} onClick={onPreviewNow} disabled={isPreviewingNow}>
              {isPreviewingNow ? 'Previewing...' : 'Preview now'}
            </button>
          ) : null}
        </div>
        {previewNowError ? <div style={styles.alert}>{previewNowError}</div> : null}
      </div>
    );
  }
  if (!selection.reasons.length) {
    return <div style={styles.helperText}>No metrics were excluded in this preview.</div>;
  }
  return (
    <div style={styles.stack}>
      <div style={{ fontWeight: 800 }}>Why metrics were excluded</div>
      {selection.reasons.map((entry) => (
        <div key={entry.label} style={{ border: '1px solid rgba(204, 204, 220, 0.16)', borderRadius: 8, padding: 10, background: 'rgba(17, 18, 23, 0.4)' }}>
          <div style={styles.rowBetween}>
            <div>
              <strong>{entry.label}</strong>
              <span style={{ ...styles.helperText, marginLeft: 8 }}>{entry.count} metric{entry.count === 1 ? '' : 's'}</span>
            </div>
            <button type="button" style={{ ...styles.button, padding: '4px 10px', fontSize: 12 }} onClick={() => setExpandedReason(expandedReason === entry.label ? null : entry.label)}>
              {expandedReason === entry.label ? 'Hide' : 'View list'}
            </button>
          </div>
          <div style={{ ...styles.helperText, marginTop: 4 }}>{entry.description}</div>
          {entry.wouldEnableCategories?.length ? (
            <div style={{ ...styles.row, marginTop: 8, flexWrap: 'wrap' }}>
              {entry.wouldEnableCategories.map((item) => (
                <span key={item.category} style={{ ...styles.chip, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  {humanize(item.category)} ({item.count})
                  {onEnableCategory ? (
                    <button
                      type="button"
                      style={{ ...styles.button, padding: '2px 8px', fontSize: 11, background: '#3fcf8e', color: '#08130e' }}
                      onClick={() => onEnableCategory(item.category as MonitoringCategory)}
                      title={`Enable the ${item.category} category and go back to Configure to preview the change.`}
                    >
                      Enable
                    </button>
                  ) : null}
                </span>
              ))}
            </div>
          ) : null}
          {expandedReason === entry.label ? (
            <div style={{ marginTop: 8, maxHeight: 220, overflowY: 'auto', display: 'grid', gap: 6 }}>
              {entry.metrics.map((metric, index) => (
                <div key={`${metric.metricName}:${metric.service ?? ''}:${index}`} style={styles.helperText}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                    <span>{metric.metricName}</span>
                    <span>{[metric.service, metric.namespace].filter(Boolean).join(' / ') || '—'}</span>
                  </div>
                  {metric.supersededByMetric ? <div style={{ color: 'rgba(204, 204, 220, 0.6)' }}>→ superseded by <strong>{metric.supersededByMetric}</strong></div> : null}
                  {formatMatchedRule(metric.matchedRule) ? <div style={{ color: 'rgba(204, 204, 220, 0.6)' }}>{formatMatchedRule(metric.matchedRule)}</div> : null}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const tone = normalized === 'completed' ? '#3fcf8e' : normalized === 'partial' ? '#ffb357' : normalized === 'failed' ? '#f2495c' : '#5794f2';
  return <span style={{ ...styles.chip, width: 'fit-content', color: tone, borderColor: `${tone}66` }}>{humanize(status)}</span>;
}

function BudgetExcludedAlert({
  metrics,
  count,
}: {
  metrics?: string[];
  count?: number;
}) {
  if (!metrics || metrics.length === 0) return null;
  const totalCount = count ?? metrics.length;
  const remaining = totalCount - 10;
  return (
    <div style={{ ...styles.alert, marginTop: 12, backgroundColor: '#22272e', borderColor: '#ffb35766' }}>
      <strong>Budget-excluded metrics ({totalCount}):</strong>{' '}
      {metrics.slice(0, 10).join(', ')}
      {remaining > 0 ? ` (and ${remaining} more)` : ''}.
      <div style={{ ...styles.muted, marginTop: 4 }}>
        Each run is independent; budget-excluded metrics are not deferred across runs. Increase max metrics per run or narrow scope to include them.
      </div>
    </div>
  );
}

function AutonomousRunPanel({ result }: { result: AutonomousRunResponse | null }) {
  if (!result) return null;
  const statusTone = result.status === 'completed' ? '#3fcf8e' : result.status === 'partial' ? '#ffb357' : '#f2495c';
  return (
    <Card>
      <div style={styles.rowBetween}>
        <div>
          <h2 style={{ margin: 0 }}>Autonomous Run Result</h2>
          <p style={{ ...styles.muted, margin: '5px 0 0' }}>
            One-shot execution from {new Date(result.requested_start).toLocaleString()} to {new Date(result.requested_end).toLocaleString()} at step {result.step}.
          </p>
        </div>
        <span style={{ ...styles.chip, color: statusTone }}>{humanize(result.status)}</span>
      </div>
      {result.warnings.map((warning) => <div key={warning} style={{ ...styles.alert, marginTop: 12 }}>{warning}</div>)}
      <div style={{ ...styles.compactStats, marginTop: 16 }}>
        <Kpi label="Planned jobs" value={result.planned_jobs} />
        <Kpi label="Executed" value={result.executed_jobs} tone="#3fcf8e" />
        <Kpi label="Skipped" value={result.skipped_jobs} />
        {result.budget_limited_jobs ? (
          <Kpi label="Budget-limited" value={result.budget_limited_jobs} tone="#ffb357" />
        ) : null}
        <Kpi label="Failed" value={result.failed_jobs} tone={result.failed_jobs ? '#f2495c' : '#d8d9da'} />
      </div>
      <BudgetExcludedAlert metrics={result.budget_excluded_metrics} count={result.budget_excluded_metrics_count} />
      <div style={{ display: 'grid', gap: 10, marginTop: 16 }}>
        {result.results.map((job) => (
          <div key={`${job.metric_name}:${job.service ?? 'unknown'}:${job.analysis_run_id ?? job.status}`} style={panelStyle(job.status === 'completed' ? '#3fcf8e' : '#f2495c')}>
            <div style={styles.rowBetween}>
              <strong>{job.service ?? 'unknown'} / {job.metric_name}</strong>
              <span style={{ color: job.status === 'completed' ? '#3fcf8e' : '#f2495c' }}>{humanize(job.status)}</span>
            </div>
            <div style={styles.helperText}>
              {job.sample_count} samples · {job.series_count} series · {job.signal_count} signals · {job.findings_count} findings · {job.behavior_findings_count} behavior findings
              {job.analysis_run_id ? ` · run ${job.analysis_run_id}` : ''}
            </div>
            {job.error && <div style={{ ...styles.alert, marginTop: 8 }}>{job.error}</div>}
            <pre style={{ ...styles.pre, marginTop: 10 }}>{job.promql}</pre>
          </div>
        ))}
      </div>
    </Card>
  );
}

function PreviewPlanPanel({
  result,
  rows,
  canRunOnce,
  isRunningOnce,
  onRunOnce,
  onBack,
  statusFilter,
  setStatusFilter,
  categoryFilter,
  setCategoryFilter,
  conceptFilter,
  setConceptFilter,
  expandedMetric,
  setExpandedMetric,
}: {
  result: AutonomousPreviewResponse | null;
  rows: AutonomousPlanItem[];
  canRunOnce: boolean;
  isRunningOnce: boolean;
  onRunOnce: () => Promise<void>;
  onBack: () => void;
  statusFilter: 'all' | 'planned' | 'excluded';
  setStatusFilter: (value: 'all' | 'planned' | 'excluded') => void;
  categoryFilter: string;
  setCategoryFilter: (value: string) => void;
  conceptFilter: string;
  setConceptFilter: (value: string) => void;
  expandedMetric: string | null;
  setExpandedMetric: (value: string | null) => void;
}) {
  if (!result) {
    return (
      <Card>
        <div style={styles.emptyHero}>
          <div>
            <h2 style={{ margin: 0 }}>Preview metric plan</h2>
            <p style={styles.muted}>Choose scope and monitoring categories, then preview. No analysis jobs are started.</p>
          </div>
        </div>
      </Card>
    );
  }
  const categories = Array.from(new Set(result.items.map((item) => item.category).filter(Boolean))) as string[];
  const concepts = Array.from(new Set(result.items.map((item) => item.concept).filter(Boolean))) as string[];
  const selectedRows = rows.filter((item) => item.planned);
  const categoryCounts = result.items.reduce<Record<string, number>>((acc, item) => {
    if (item.planned && item.category) acc[item.category] = (acc[item.category] ?? 0) + 1;
    return acc;
  }, {});
  return (
    <Card>
      <div style={styles.rowBetween}>
        <div>
          <h2 style={{ margin: 0 }}>Metric Plan Preview</h2>
          <p style={{ ...styles.muted, margin: '5px 0 0' }}>Review selected and excluded metric groups before starting autonomous analysis.</p>
        </div>
        <span style={{ ...styles.chip, color: '#3fcf8e' }}>{result.planned_jobs} planned jobs</span>
      </div>
      {result.warnings.map((warning) => <div key={warning} style={{ ...styles.alert, marginTop: 12 }}>{warning}</div>)}
      <div style={{ ...styles.compactStats, marginTop: 16 }}>
        <Kpi label="Metrics discovered" value={result.metrics_discovered} />
        <Kpi label="Selected by monitoring policy" value={result.metrics_selected ?? result.metrics_matched} tone="#3fcf8e" />
        <Kpi label="Excluded" value={result.metrics_excluded} tone="#ffb357" />
        {result.budget_limited_jobs ? (
          <Kpi label="Budget-limited" value={result.budget_limited_jobs} tone="#ffb357" />
        ) : null}
      </div>
      <BudgetExcludedAlert metrics={result.budget_excluded_metrics} count={result.budget_excluded_metrics_count} />
      <div style={{ ...styles.infoNote, marginTop: 12 }}>Statistical candidate screening is not enabled yet.</div>
      {result.monitoring_summary?.concepts?.length ? (
        <div style={{ ...styles.infoNote, marginTop: 12 }}>
          Intent expanded to concepts: {result.monitoring_summary.concepts.map(humanize).join(', ')}
        </div>
      ) : null}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(180px, 0.35fr) minmax(0, 1fr)', gap: 16, marginTop: 16 }}>
        <div style={panelStyle('#5794f2')}>
          <h3 style={sectionTitleStyle}>Selected by category</h3>
          {Object.keys(categoryCounts).length ? Object.entries(categoryCounts).map(([category, count]) => (
            <div key={category} style={styles.rowBetween}>
              <span>{humanize(category)}</span>
              <strong>{count}</strong>
            </div>
          )) : <p style={styles.muted}>No selected categories returned.</p>}
        </div>
        <div style={panelStyle('#3fcf8e')}>
          <h3 style={sectionTitleStyle}>Selected metrics</h3>
          {!selectedRows.length ? (
            <div style={styles.emptyHero}>
              <p>No metrics matched the current scope and monitoring categories.</p>
              <p style={styles.muted}>Adjust the service, namespace, or monitoring selections and preview again.</p>
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: '0.9fr 1.4fr 0.9fr 1fr', gap: '10px 14px', fontSize: 12 }}>
              {['Service', 'Metric', 'Category', 'Reason'].map((header) => <div key={header} style={styles.tableHeader}>{header}</div>)}
              {selectedRows.slice(0, 25).map((item) => (
                <React.Fragment key={`${item.service ?? 'unknown'}:${item.metric_name}:${item.category ?? 'none'}`}>
                  <div>{item.service ?? 'unknown'}</div>
                  <button type="button" style={styles.tableRowButton} onClick={() => setExpandedMetric(expandedMetric === item.metric_name ? null : item.metric_name)}>{item.metric_name}</button>
                  <div>{item.category ? humanize(item.category) : 'Unmatched'}</div>
                  <div>{humanize(item.selection_reason ?? 'policy match')}</div>
                  {expandedMetric === item.metric_name && (
                    <div style={{ gridColumn: '1 / -1', ...styles.answerCard }}>
                      {previewRowExplanation(item)}
                      {item.promql && <pre style={{ ...styles.pre, marginTop: 10 }}>{item.promql}</pre>}
                    </div>
                  )}
                </React.Fragment>
              ))}
              {selectedRows.length > 25 ? <div style={{ gridColumn: '1 / -1', ...styles.helperText }}>+ {selectedRows.length - 25} more selected metrics</div> : null}
            </div>
          )}
        </div>
      </div>
      <div style={{ ...styles.row, marginTop: 16 }}>
        <button type="button" style={{ ...styles.button, background: 'rgba(204, 204, 220, 0.14)' }} onClick={onBack}>
          Back to configuration
        </button>
        <button type="button" style={canRunOnce ? { ...styles.button, background: 'linear-gradient(135deg, #3fcf8e, #197a4d)' } : { ...styles.button, ...styles.buttonDisabled, background: 'rgba(63, 207, 142, 0.2)' }} disabled={!canRunOnce} onClick={onRunOnce}>
          {isRunningOnce ? 'Running autonomous analysis...' : 'Run autonomous analysis once'}
        </button>
      </div>
      <div style={{ ...styles.row, marginTop: 16 }}>
        <Field label="Status filter">
          <select style={styles.input} value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as 'all' | 'planned' | 'excluded')}>
            <option value="all">All rows</option>
            <option value="planned">Selected only</option>
            <option value="excluded">Excluded only</option>
          </select>
        </Field>
        <Field label="Category filter">
          <select style={styles.input} value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}>
            <option value="all">All categories</option>
            {categories.map((category) => <option key={category} value={category}>{humanize(category)}</option>)}
          </select>
        </Field>
        <Field label="Concept filter">
          <select style={styles.input} value={conceptFilter} onChange={(event) => setConceptFilter(event.target.value)}>
            <option value="all">All concepts</option>
            {concepts.map((concept) => <option key={concept} value={concept}>{humanize(concept)}</option>)}
          </select>
        </Field>
      </div>
      {!rows.length && selectedRows.length ? <div style={styles.emptyHero}><p>No preview rows match the current filters.</p></div> : null}
    </Card>
  );
}

function PreviewLoadingPanel() {
  return (
    <Card>
      <div>
        <h2 style={{ margin: 0 }}>Building metric plan...</h2>
        <p style={{ ...styles.muted, margin: '5px 0 0' }}>Previewing the metrics that match the current scope and monitoring policy.</p>
      </div>
      <div style={{ ...styles.stack, marginTop: 16 }}>
        {['Discovering metrics', 'Applying monitoring policy', 'Preparing selected metrics'].map((step) => (
          <div key={step} style={panelStyle('#5794f2')}>
            <strong>{step}</strong>
          </div>
        ))}
      </div>
    </Card>
  );
}

function PreviewErrorPanel({ onRetry, onBack }: { onRetry: () => Promise<void>; onBack: () => void }) {
  return (
    <Card>
      <div style={styles.emptyHero}>
        <div>
          <h2 style={{ margin: 0 }}>Metric plan could not be loaded.</h2>
          <p style={styles.muted}>Check the backend connection or adjust the selected scope, then try again.</p>
          <div style={{ ...styles.row, justifyContent: 'center', marginTop: 16 }}>
            <button type="button" style={{ ...styles.button, background: 'rgba(204, 204, 220, 0.14)' }} onClick={onBack}>
              Back to configuration
            </button>
            <button type="button" style={styles.button} onClick={onRetry}>
              Retry
            </button>
          </div>
        </div>
      </div>
    </Card>
  );
}

function AutonomousRunningPanel({ plannedJobs }: { plannedJobs: number | null }) {
  return (
    <Card>
      <div style={styles.rowBetween}>
        <div>
          <h2 style={{ margin: 0 }}>Autonomous analysis is running...</h2>
          <p style={{ ...styles.muted, margin: '5px 0 0' }}>The overview will appear when the run completes.</p>
        </div>
        <span style={{ ...styles.chip, color: '#3fcf8e' }}>Run once</span>
      </div>
      <div style={{ ...styles.stack, marginTop: 18 }}>
        <ProgressRow label="Discovering metrics" status="complete" />
        <ProgressRow label="Building metric plan" status="complete" />
        <ProgressRow label="Executing analysis jobs" status="running" detail={plannedJobs ? `${plannedJobs} planned jobs` : 'In progress'} />
        <ProgressRow label="Aggregating findings" status="pending" />
        <ProgressRow label="Preparing overview" status="pending" />
      </div>
      <div style={{ ...styles.alert, marginTop: 18 }}>
        You can keep this page open. The results view will replace this progress state when the run completes.
      </div>
    </Card>
  );
}

function ProgressRow({ label, status, detail }: { label: string; status: 'complete' | 'running' | 'pending'; detail?: string }) {
  const marker = status === 'complete' ? '✓' : status === 'running' ? '⟳' : '○';
  const tone = status === 'complete' ? '#3fcf8e' : status === 'running' ? '#5794f2' : 'rgba(204, 204, 220, 0.62)';
  return (
    <div style={{ ...styles.rowBetween, borderBottom: '1px solid rgba(204, 204, 220, 0.1)', padding: '10px 0' }}>
      <div style={{ ...styles.row, gap: 10 }}>
        <span style={{ color: tone, fontWeight: 900 }}>{marker}</span>
        <strong>{label}</strong>
      </div>
      <span style={{ ...styles.helperText, marginTop: 0 }}>{detail ?? humanize(status)}</span>
    </div>
  );
}

function RunErrorPanel({ result, onRetry, onBack }: { result: AutonomousRunResponse | null; onRetry: () => Promise<void>; onBack: () => void }) {
  const failedJobs = result?.results?.filter((job) => job.status === 'failed' || job.error).slice(0, 5) ?? [];
  return (
    <Card>
      <div style={styles.emptyHero}>
        <div>
          <h2 style={{ margin: 0 }}>Autonomous analysis could not be completed.</h2>
          <p style={styles.muted}>The metric plan is still available. Retry the run or return to configuration.</p>
          {result ? (
            <div style={{ ...styles.compactStats, marginTop: 16, textAlign: 'left' }}>
              <Kpi label="Planned jobs" value={result.planned_jobs} />
              <Kpi label="Completed" value={result.executed_jobs} tone="#3fcf8e" />
              <Kpi label="Skipped" value={result.skipped_jobs} tone="#ffb357" />
              <Kpi label="Failed" value={result.failed_jobs} tone="#f2495c" />
            </div>
          ) : null}
          {result?.warnings?.length ? (
            <div style={{ ...styles.stack, textAlign: 'left', marginTop: 16 }}>
              {result.warnings.slice(0, 3).map((warning) => (
                <div key={warning} style={panelStyle('#f2495c')}>{warning}</div>
              ))}
            </div>
          ) : null}
          {failedJobs.length ? (
            <div style={{ ...styles.stack, textAlign: 'left', marginTop: 16 }}>
              {failedJobs.map((job) => (
                <div key={`${job.service ?? 'unknown'}:${job.metric_name}:${job.promql}`} style={panelStyle('#f2495c')}>
                  <div style={styles.rowBetween}>
                    <strong>{job.service ?? 'unknown'} / {job.metric_name}</strong>
                    <span style={{ color: '#f2495c' }}>{humanize(job.status)}</span>
                  </div>
                  {job.error ? <div style={{ ...styles.alert, marginTop: 8 }}>{job.error}</div> : null}
                  {job.promql ? <pre style={{ ...styles.pre, marginTop: 10 }}>{job.promql}</pre> : null}
                </div>
              ))}
            </div>
          ) : null}
          <div style={{ ...styles.row, justifyContent: 'center', marginTop: 16 }}>
            <button type="button" style={{ ...styles.button, background: 'rgba(204, 204, 220, 0.14)' }} onClick={onBack}>
              Back to configuration
            </button>
            <button type="button" style={styles.button} onClick={onRetry}>
              Retry run
            </button>
          </div>
        </div>
      </div>
    </Card>
  );
}

function formatNullableCount(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString() : '—';
}

function formatCompactDate(value?: string | null) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString(undefined, { month: 'numeric', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

function humanize(value: string) {
  return value.replace(/[_-]+/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function panelStyle(tone: string): React.CSSProperties {
  return {
    border: `1px solid ${tone}44`,
    borderRadius: 8,
    padding: 14,
    background: `linear-gradient(135deg, ${tone}12, rgba(17, 18, 23, 0.72) 46%)`,
  };
}

const sectionTitleStyle: React.CSSProperties = { margin: '0 0 12px', fontSize: 15 };
