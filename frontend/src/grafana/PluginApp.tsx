import React from 'react';
import { useEffect, useMemo, useState } from 'react';
import { answerAutonomousQuestion, createCaseFromFinding, createCaseTicket, getCase, getCaseTicket, getTicketingStatus, listAnalysisRuns, listAutonomousPolicies, listAutonomousPolicyRuns, listAutonomousScopeOptions, listBehaviorFindings, listCases, listFindings, listPrometheusConnections, listPrometheusLabelValues, previewAutonomousPlan, runAutonomousPlanOnce, runConnectionAnalysis, runPrometheusSampleAnalysis, saveAutonomousPolicy, searchFindings, setAutonomousPolicyStatus, syncCaseTicket, testPrometheusConnection, updateAutonomousPolicy, type AutonomousQuestionAnswer, type FindingsWindow } from './backendClient';
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
import { activeBackendUrl, backendOptionsFor, configuredBackendUrl, configuredWebUiUrl, isGrafanaProxyUrl, localBackendOptions, type BackendOption, type PluginJsonData } from './backendUrlSetting';
import { ApiTokenField } from './ApiTokenField';
import { Card, Field, styles } from './plainUi';
import { PluginSetupBanner, SetupChips, useSetupCheck } from './SetupCheckPanel';
import { asGrafanaRole, grafanaUserRole, LockReason, LOCK_REASONS, PermissionsProvider, usePermissions } from './permissions';
import { behaviorAnchor, PluginBehaviorFindings } from './PluginBehaviorFindings';
import { WebUiContext } from './webUiLink';
import { useSectionShown } from './sectionToggle';
import { patternParts, patternsByFinding } from '../utils/combinedPatterns';
import { PluginBreakdownDisclosure, PluginBreakdownSection, PluginScopeChip } from './PluginBreakdown';
import { PluginFindingTrust } from './PluginFindingTrust';
import { PluginCustomSettings, PluginCustomSettingsChip } from './PluginCustomSettings';
import { PluginPlainBadge, PluginPlainFinding } from './PluginPlainFinding';
import { PluginMemoryAlertsView } from './PluginMemoryAlertsView';
import { connectionName, findingClusters, findingSource, findingsInCluster } from './findingSource';
import { casesInService, inService, serviceOptions, showServiceFilter, type ServiceOption } from '../utils/serviceFilter';
import { readServiceParam, writeServiceParam } from './serviceUrlState';
import { caseForSymptom, caseIdsByFinding, dataProblemsByMetric, NO_SERVICE, serviceLabel, serviceSymptoms, stillShowing, symptomChange, symptomKey, symptomKind, symptomOf, symptomRole, triageOrder, triageSymptoms, type ServiceSymptom, type SymptomTriage } from './serviceSymptoms';
import { PluginSeenBefore } from './PluginSeenBefore';
import { shouldShowTicketCard } from '../utils/ticketingVisibility';
import { findingBreakdown } from '../utils/findingBreakdown';
import { findingLevel } from '../utils/findingLevel';
import { byLine, scheduleAuthorLine } from '../utils/actorLine';
import { buildMetricQuery, buildServiceMatcher, type MetricMode } from './prometheusQueryBuilder';
import { normalizePrometheusFrames } from './prometheusFrameNormalizer';
import type { AutonomousPlanItem, AutonomousPolicy, AutonomousPreviewResponse, AutonomousRunResponse, CaseTicketLink, CaseTicketOperation, GrafanaAnalysisResult, GrafanaCase, GrafanaQueryTarget, MonitoringCategory } from './contracts';
import type { AnalysisRun, BehaviorFinding, Finding, PrometheusConnection } from '../types';
import { autonomousSourceFor, buildAutonomousPreviewRequest, filterPreviewRows, previewRowExplanation } from './autonomousPreviewModel';
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

const timePresets = [
  { label: 'Last 30m', hours: 0.5 },
  { label: 'Last 1h', hours: 1 },
  { label: 'Last 6h', hours: 6 },
  { label: 'Last 24h', hours: 24 },
];

type PluginMode = 'interactive' | 'autonomous' | 'memory';
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
  { id: 'custom', title: 'Custom', detail: 'Your own metric names or patterns' },
] satisfies Array<{ id: MonitoringCategory; title: string; detail: string }>;

export function PluginApp(props: { meta?: { jsonData?: PluginJsonData } }) {
  const buildDefaultBackendUrl = import.meta.env.VITE_OPS_SIGNALS_BACKEND_URL;
  // Through Grafana when the admin chose it on the Configuration page; otherwise straight to the backend.
  const defaultBackendUrl = activeBackendUrl(props.meta?.jsonData, buildDefaultBackendUrl);
  const backendOptions = useMemo(() => backendOptionsFor(props.meta?.jsonData, buildDefaultBackendUrl), [props.meta?.jsonData, buildDefaultBackendUrl]);
  const [activeMode, setActiveMode] = useState<PluginMode>('interactive');
  const [target, setTarget] = useState<GrafanaQueryTarget>(defaultTarget);
  const [result, setResult] = useState<GrafanaAnalysisResult | null>(null);
  const [backendUrl, setBackendUrl] = useState(defaultBackendUrl);
  const [prometheusDatasources, setPrometheusDatasources] = useState<PrometheusDatasourceRef[]>([]);
  const [selectedPrometheusUid, setSelectedPrometheusUid] = useState('');
  const [serviceLabel, setServiceLabel] = useState('service');
  const [metricMode, setMetricMode] = useState<MetricMode>('metric');
  // Interactive Analysis can query a Grafana data source (as before) or a backend connection (one per
  // Mimir tenant), which also picks a cluster and tags the run with it, as the web UI's Validate Data.
  const [interactiveSource, setInteractiveSource] = useState<'grafana' | 'connection'>('grafana');
  const [interactiveConnectionId, setInteractiveConnectionId] = useState<string | null>(null);
  const [interactiveCluster, setInteractiveCluster] = useState('');
  const [connectionServices, setConnectionServices] = useState<string[]>([]);
  const [connectionMetrics, setConnectionMetrics] = useState<string[]>([]);
  const [connectionClusterOptions, setConnectionClusterOptions] = useState<string[]>([]);
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
  // Which backend Prometheus connection (Mimir tenant) and clusters autonomous analysis covers.
  const [autonomousConnections, setAutonomousConnections] = useState<PrometheusConnection[]>([]);
  const [autonomousConnectionId, setAutonomousConnectionId] = useState<string | null>(null);
  const [autonomousClusterOptions, setAutonomousClusterOptions] = useState<string[]>([]);
  const [autonomousClusterLabel, setAutonomousClusterLabel] = useState<string | null>(null);
  const [autonomousAllClusters, setAutonomousAllClusters] = useState(true);
  const [autonomousClusters, setAutonomousClusters] = useState<string[]>([]);
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

  /** `quiet` refreshes in place (after a case is created): no loading screen, and a failed refresh
   * keeps what is shown instead of replacing it with the error screen. */
  async function refreshAutonomousOverview(active = true, quiet = false) {
    if (!quiet) {
      setIsLoadingOverview(true);
      setOverviewError('');
      setOverviewEndpointErrors([]);
    }
    const overviewRequests = [
      { component: 'Discovery & Selection / Execution History', apiFunction: 'listAnalysisRuns', endpoint: '/api/analysis-runs?limit=25', run: () => listAnalysisRuns(backendUrl) },
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

      if (errors.length && !quiet) {
        setOverviewEndpointErrors(errors);
        setOverviewError('Autonomous monitoring summary could not be loaded.');
      }
    } catch {
      if (!active || quiet) return;
      setOverviewError('Autonomous monitoring summary could not be loaded.');
    } finally {
      if (active && !quiet) setIsLoadingOverview(false);
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
    if (activeMode === 'memory' || !backendUrl) return;
    listPrometheusConnections(backendUrl)
      .then((response) => { if (active) setAutonomousConnections(response.connections); })
      .catch(() => { if (active) setAutonomousConnections([]); });
    return () => {
      active = false;
    };
  }, [activeMode, backendUrl]);

  // Until one is picked (or a saved schedule sets it), the backend's default connection.
  const autonomousEffectiveConnectionId = autonomousSourceFor({
    connections: autonomousConnections, pickedConnectionId: autonomousConnectionId, allClusters: true, pickedClusters: [], clusterOptions: [],
  }).connectionId ?? null;

  useEffect(() => {
    let active = true;
    if (activeMode !== 'autonomous' || !backendUrl) return;
    listAutonomousScopeOptions(backendUrl, { serviceLabel, namespaceLabel, environmentLabel, window: analysisWindow, connectionId: autonomousEffectiveConnectionId })
      .then((options) => {
        if (!active) return;
        setServices(options.services);
        setNamespaces(options.namespaces);
        setAutonomousClusterOptions(options.clusters ?? []);
        setAutonomousClusterLabel(options.cluster_label ?? null);
      })
      .catch(() => {
        // Keep Grafana-discovered values as a graceful fallback.
      });
    return () => {
      active = false;
    };
  }, [activeMode, backendUrl, serviceLabel, namespaceLabel, environmentLabel, analysisWindow, autonomousEffectiveConnectionId]);

  const autonomousSource = autonomousSourceFor({
    connections: autonomousConnections,
    pickedConnectionId: autonomousConnectionId,
    allClusters: autonomousAllClusters,
    pickedClusters: autonomousClusters,
    clusterOptions: autonomousClusterOptions,
  });

  const selectedDatasource = useMemo(
    () => prometheusDatasources.find((datasource) => datasource.uid === selectedPrometheusUid),
    [prometheusDatasources, selectedPrometheusUid]
  );
  // The header chips and the setup reminder both come from one Setup check of the chosen backend.
  const setup = useSetupCheck(backendUrl, configuredBackendUrl(props.meta?.jsonData));
  // Roles apply only through Grafana, where the backend enforces them too (backend/app/roles.py).
  const role = isGrafanaProxyUrl(backendUrl) ? asGrafanaRole(setup.result?.you?.role) ?? grafanaUserRole() : null;
  const timeRangeValid = timeRange.from.getTime() < timeRange.to.getTime();

  // --- Interactive Analysis through a backend connection ---
  const interactiveConnection = autonomousConnections.find((connection) => connection.id === interactiveConnectionId)
    ?? autonomousConnections.find((connection) => connection.is_default)
    ?? null;
  const interactiveClusterLabel = interactiveConnection?.cluster_label ?? null;
  const connectionServiceMatcher = (() => {
    try {
      return target.service ? `{${buildServiceMatcher(serviceLabel || 'service', target.service)}}` : null;
    } catch {
      return null;
    }
  })();
  const connectionSeriesSelector = (() => {
    if (metricMode !== 'metric' || !target.service || !target.metric) return null;
    try {
      return buildMetricQuery({ metric: target.metric, mode: 'metric', service: target.service, serviceLabel });
    } catch {
      return null;
    }
  })();
  // A Cluster choice appears only when the series exists in several clusters; the backend analyses
  // exactly one series per run. A choice no longer in the list doesn't apply.
  const needsCluster = interactiveSource === 'connection' && connectionClusterOptions.length > 1;
  const chosenCluster = needsCluster && connectionClusterOptions.includes(interactiveCluster) ? interactiveCluster : '';
  const ready = interactiveSource === 'connection'
    ? Boolean(interactiveConnection && target.service && target.metric && (!needsCluster || chosenCluster))
    : Boolean(selectedPrometheusUid && target.service && target.metric);

  useEffect(() => {
    if (activeMode !== 'interactive' || interactiveSource !== 'connection' || !backendUrl || !interactiveConnection) return;
    let active = true;
    listPrometheusLabelValues(backendUrl, serviceLabel || 'service', interactiveConnection.id)
      .then((response) => { if (active) setConnectionServices(response.values); })
      .catch(() => { if (active) setConnectionServices([]); });
    return () => { active = false; };
  }, [activeMode, interactiveSource, backendUrl, interactiveConnection?.id, serviceLabel]);

  useEffect(() => {
    if (activeMode !== 'interactive' || interactiveSource !== 'connection' || !backendUrl || !interactiveConnection) return;
    let active = true;
    // The metrics the chosen service has, else every metric name.
    listPrometheusLabelValues(backendUrl, '__name__', interactiveConnection.id, connectionServiceMatcher ? { match: [connectionServiceMatcher] } : undefined)
      .then((response) => { if (active) setConnectionMetrics(response.values.slice(0, 500)); })
      .catch(() => { if (active) setConnectionMetrics([]); });
    return () => { active = false; };
  }, [activeMode, interactiveSource, backendUrl, interactiveConnection?.id, connectionServiceMatcher]);

  const rangeStart = timeRange.from.toISOString();
  const rangeEnd = timeRange.to.toISOString();
  useEffect(() => {
    setConnectionClusterOptions([]);
    if (activeMode !== 'interactive' || interactiveSource !== 'connection' || !backendUrl || !interactiveConnection || !interactiveClusterLabel || !connectionSeriesSelector) return;
    let active = true;
    listPrometheusLabelValues(backendUrl, interactiveClusterLabel, interactiveConnection.id, { match: [connectionSeriesSelector], start: rangeStart, end: rangeEnd })
      .then((response) => { if (active) setConnectionClusterOptions(response.values); })
      .catch(() => undefined);
    return () => { active = false; };
  }, [activeMode, interactiveSource, backendUrl, interactiveConnection?.id, interactiveClusterLabel, connectionSeriesSelector, rangeStart, rangeEnd]);

  async function runConnectionInteractive() {
    if (!interactiveConnection) return;
    const startedAt = performance.now();
    const clusterSelector = chosenCluster && interactiveClusterLabel ? { label: interactiveClusterLabel, value: chosenCluster } : null;
    const promql = buildMetricQuery({ metric: target.metric, mode: metricMode, service: target.service, serviceLabel, cluster: clusterSelector });
    setStage(`Querying ${interactiveConnection.name}: ${promql}`);
    const backendResult = await runConnectionAnalysis(backendUrl, {
      connectionId: interactiveConnection.id,
      connectionName: interactiveConnection.name,
      service: target.service,
      metric: target.metric,
      promql,
      from: timeRange.from.toISOString(),
      to: timeRange.to.toISOString(),
      stepSeconds: Math.max(Math.round(calculateIntervalMs(timeRange) / 1000), 1),
      cluster: chosenCluster || null,
      startedAt,
    });
    setResult(backendResult);
  }

  async function runInteractiveAnalysis() {
    if (!ready || !timeRangeValid) return;
    setIsRunning(true);
    setError('');
    setStage('Resolving Prometheus datasource');
    const startedAt = performance.now();
    try {
      if (interactiveSource === 'connection') {
        await runConnectionInteractive();
        return;
      }
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
      setError(`${stage || 'Analysis'} failed. ${interactiveSource === 'connection' ? message.replace(/^Request failed: \d+ - /, '') : message}`);
    } finally {
      setIsRunning(false);
      setStage('');
    }
  }

  // Set when Autonomous Analysis hands a finding over: run it once the form has its service and
  // metric, so the user lands on results rather than an unrun form.
  const [pendingInteractiveRun, setPendingInteractiveRun] = useState(false);
  useEffect(() => {
    if (!pendingInteractiveRun || activeMode !== 'interactive' || isRunning) return;
    // Through a connection the form is ready only once the finding's cluster is in the cluster list.
    if (!(ready && timeRangeValid)) return;
    setPendingInteractiveRun(false);
    void runInteractiveAnalysis();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingInteractiveRun, activeMode, ready, timeRangeValid, isRunning]);
  // A hand-over that never becomes runnable (e.g. the series is gone) doesn't fire later on its own.
  useEffect(() => {
    if (!pendingInteractiveRun) return;
    const timer = window.setTimeout(() => setPendingInteractiveRun(false), 15000);
    return () => window.clearTimeout(timer);
  }, [pendingInteractiveRun]);
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

  function applyCustomRange(fromInput = timeFromInput, toInput = timeToInput) {
    const nextFrom = parseDateTimeLocal(fromInput);
    const nextTo = parseDateTimeLocal(toInput);
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
    <PermissionsProvider role={role}>
    <WebUiContext.Provider value={configuredWebUiUrl(props.meta?.jsonData) ?? null}>
    <main style={styles.shell}>
      <div>
        <h1 style={{ margin: 0 }}>Ops Signals</h1>
        <p style={{ ...styles.muted, margin: '6px 0 0' }}>Operational changes detected from the selected Grafana metric and time range.</p>
        {/* Their own row from the start: one chip while checking, up to four after, and the page
            below doesn't move when they arrive. */}
        <div style={{ ...styles.row, gap: 8, marginTop: 10, minHeight: 26 }}>
          <SetupChips result={setup.result} unreachable={setup.unreachable} />
        </div>
      </div>

      <PluginSetupBanner result={setup.result} unreachable={setup.unreachable} />
      {error && <div style={styles.alert}>{error}</div>}
      {stage && <div style={styles.alert}>{stage}</div>}

      <ModeTabs activeMode={activeMode} onChange={setActiveMode} />

      {activeMode === 'memory' ? (
        <PluginMemoryAlertsView backendUrl={backendUrl} />
      ) : activeMode === 'interactive' ? (
        <>
          <InteractiveAnalysisCard
            source={interactiveSource}
            setSource={(next) => {
              setInteractiveSource(next);
              setResult(null);
            }}
            connections={autonomousConnections}
            connectionId={interactiveConnection?.id ?? null}
            setConnectionId={(id) => {
              setInteractiveConnectionId(id);
              setInteractiveCluster('');
              setResult(null);
            }}
            connectionServices={connectionServices}
            connectionMetrics={connectionMetrics}
            clusterOptions={needsCluster ? connectionClusterOptions : []}
            cluster={chosenCluster}
            setCluster={setInteractiveCluster}
            prometheusDatasources={prometheusDatasources}
            selectedPrometheusUid={selectedPrometheusUid}
            setSelectedPrometheusUid={setSelectedPrometheusUid}
            backendUrl={backendUrl}
            setBackendUrl={setBackendUrl}
            backendOptions={backendOptions}
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
            onRun={runInteractiveAnalysis}
          />
          <PanelPreview result={result} backendUrl={backendUrl} />
        </>
      ) : (
        <AutonomousAnalysisView
          backendUrl={backendUrl}
          setBackendUrl={setBackendUrl}
          backendOptions={backendOptions}
          selectedPrometheusUid={selectedPrometheusUid}
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
          connections={autonomousConnections}
          connectionId={autonomousEffectiveConnectionId}
          setConnectionId={(id) => {
            // Another tenant has other services and clusters; keep no selection from the previous one,
            // as the web UI does - and no preview, which was for the other tenant.
            setPreviewResult(null);
            setPreviewError('');
            setAutonomousConnectionId(id);
            setAutonomousServices([]);
            setAutonomousNamespaces([]);
            setAutonomousClusters([]);
            setAutonomousAllClusters(true);
          }}
          clusterOptions={autonomousClusterOptions}
          clusterLabel={autonomousClusterLabel}
          allClusters={autonomousAllClusters}
          setAllClusters={setAutonomousAllClusters}
          selectedClusters={autonomousClusters}
          setSelectedClusters={setAutonomousClusters}
          source={autonomousSource}
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
            setAutonomousCaseError('');
          }}
          onInvestigateInteractive={(finding) => {
            setTarget((current) => ({
              ...current,
              service: finding.service || current.service,
              metric: finding.metric_name || current.metric,
            }));
            setMetricMode('metric');
            // A finding from a backend connection (a Mimir tenant, maybe one of several clusters) is
            // re-run on that connection and cluster; others through the Grafana data source.
            const fromConnection = finding.connection_id && autonomousConnections.some((connection) => connection.id === finding.connection_id);
            setInteractiveSource(fromConnection ? 'connection' : 'grafana');
            if (fromConnection) setInteractiveConnectionId(finding.connection_id ?? null);
            setInteractiveCluster(finding.cluster ?? '');
            setActiveMode('interactive');
            setAutonomousInvestigationFinding(null);
            setPendingInteractiveRun(true);
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
              return null;
            }
            setIsCreatingAutonomousCase(true);
            setAutonomousCaseError('');
            try {
              const createdCase = await createCaseFromFinding(backendUrl, finding.id);
              // Cases and counts below catch up in place; the finding stays on screen.
              void refreshAutonomousOverview(true, true);
              return createdCase.case_id;
            } catch {
              setAutonomousCaseError('Could not create an investigation case for this finding.');
              return null;
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
            setAutonomousCaseError('');
            try {
              const response = await previewAutonomousPlan(backendUrl, buildAutonomousPreviewRequest({
                ...autonomousSource,
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
                ...(policy.connection_id ? { connection_id: policy.connection_id } : {}),
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
                ...autonomousSource,
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
    </WebUiContext.Provider>
    </PermissionsProvider>
  );
}

/** Which clusters autonomous analysis covers. Always shown, like Services and Namespaces, so it is
 * clear whether the connection has clusters at all; the list appears when there is a choice, or when
 * a saved schedule is narrowed to clusters (kept visible even if the connection no longer has them). */
export function ClustersField({ clusterOptions, clusterLabel, allClusters, setAllClusters, selectedClusters, setSelectedClusters }: {
  clusterOptions: string[];
  clusterLabel: string | null;
  allClusters: boolean;
  setAllClusters: (value: boolean) => void;
  selectedClusters: string[];
  setSelectedClusters: (value: string[]) => void;
}) {
  const options = [...new Set([...clusterOptions, ...(allClusters ? [] : selectedClusters)])].sort();
  const label = clusterLabel ?? 'cluster';
  if (!clusterLabel) {
    return (
      <Field label="Clusters">
        <div style={styles.helperText}>Turned off for this connection (no cluster label is set), so its data is analysed as one.</div>
      </Field>
    );
  }
  if (options.length === 0) {
    return (
      <Field label="Clusters">
        <div style={{ ...styles.muted, fontSize: 13 }}>No clusters</div>
        <div style={styles.helperText}>This connection's data has no "{label}" label, so it is analysed as one.</div>
      </Field>
    );
  }
  if (options.length === 1 && allClusters) {
    return (
      <Field label="Clusters">
        <span style={styles.chip}>{options[0]}</span>
        <div style={styles.helperText}>The only cluster on this connection (label "{label}").</div>
      </Field>
    );
  }
  return (
    <Field label="Clusters">
      <label style={{ ...styles.row, marginBottom: 8 }}>
        <input type="checkbox" checked={allClusters} onChange={(event) => setAllClusters(event.target.checked)} />
        <span>All clusters</span>
      </label>
      <select
        aria-label="Clusters"
        style={{ ...styles.input, minHeight: 72 }}
        multiple
        disabled={allClusters}
        value={selectedClusters}
        onChange={(event) => setSelectedClusters(Array.from(event.target.selectedOptions).map((option) => option.value))}
      >
        {options.map((cluster) => (
          <option key={cluster} value={cluster}>{cluster}{clusterOptions.includes(cluster) ? '' : ' (not on this connection now)'}</option>
        ))}
      </select>
      <div style={styles.helperText}>Each cluster is analysed separately (label "{label}"), as when several clusters share one Mimir or Thanos.</div>
    </Field>
  );
}

/** Picks the backend Prometheus connection (one per Mimir tenant), with a connection test. */
export function ConnectionPicker({ backendUrl, connections, connectionId, onChange, compact = false, disabled = false }: {
  backendUrl: string;
  connections: PrometheusConnection[];
  connectionId: string | null;
  onChange: (value: string) => void;
  /** Just the select, Test and its result: for a form that labels and explains the choice itself. */
  compact?: boolean;
  disabled?: boolean;
}) {
  const [test, setTest] = useState<{ status: 'idle' | 'testing' } | { status: 'done'; ok: boolean; message: string }>({ status: 'idle' });
  const runTest = async () => {
    if (!connectionId) return;
    setTest({ status: 'testing' });
    try {
      const result = await testPrometheusConnection(backendUrl, connectionId);
      setTest({ status: 'done', ok: result.available, message: result.available ? `Connected${result.latency_ms ? ` · ${Math.round(result.latency_ms)} ms` : ''}` : result.message });
    } catch (error) {
      setTest({ status: 'done', ok: false, message: error instanceof Error ? error.message : 'Connection test failed' });
    }
  };
  const picker = (
      <div style={{ ...styles.row, gap: 8, flexWrap: 'nowrap' }}>
        <select
          aria-label="Prometheus connection"
          style={{ ...styles.input, ...(disabled ? { opacity: 0.4 } : {}) }}
          disabled={disabled}
          value={connectionId ?? ''}
          onChange={(event) => {
            setTest({ status: 'idle' });
            onChange(event.target.value);
          }}
        >
          {connections.map((connection) => (
            <option key={connection.id} value={connection.id}>{connection.name}{connection.configured ? '' : ' (not configured)'}</option>
          ))}
        </select>
        <button type="button" style={{ ...styles.chip, background: 'transparent', color: 'inherit', cursor: 'pointer', ...(disabled ? { opacity: 0.4 } : {}) }} disabled={disabled || test.status === 'testing' || !connectionId} onClick={runTest}>
          {test.status === 'testing' ? 'Testing...' : 'Test'}
        </button>
      </div>
  );
  const result = test.status === 'done' ? <div style={{ ...styles.helperText, color: test.ok ? '#3fcf8e' : '#ff7381' }}>{test.message}</div> : null;
  if (compact) {
    return (
      <div style={{ minWidth: 0 }}>
        {picker}
        {result}
      </div>
    );
  }
  return (
    <Field label="Prometheus connection">
      {picker}
      {result}
      <div style={styles.helperText}>One per Mimir tenant or Prometheus server, set on the backend. Services and clusters below come from it.</div>
    </Field>
  );
}

function ModeTabs({ activeMode, onChange }: { activeMode: PluginMode; onChange: (mode: PluginMode) => void }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10, maxWidth: 1080 }}>
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
      <ModeTab
        active={activeMode === 'memory'}
        title="Memory & Alerts"
        subtitle="Ask, recurring problems, received alerts"
        tone="#b877d9"
        onClick={() => onChange('memory')}
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

export type InteractiveCardProps = {
  /** Where the data comes from: a Grafana data source, or a backend connection (Mimir tenant). */
  source: 'grafana' | 'connection';
  setSource: (value: 'grafana' | 'connection') => void;
  connections: PrometheusConnection[];
  connectionId: string | null;
  setConnectionId: (value: string) => void;
  connectionServices: string[];
  connectionMetrics: string[];
  /** Clusters the chosen series exists in; empty unless there is a choice to make. */
  clusterOptions: string[];
  cluster: string;
  setCluster: (value: string) => void;
  prometheusDatasources: PrometheusDatasourceRef[];
  selectedPrometheusUid: string;
  setSelectedPrometheusUid: (value: string) => void;
  backendUrl: string;
  setBackendUrl: (value: string) => void;
  backendOptions?: BackendOption[];
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
  applyCustomRange: (fromInput?: string, toInput?: string) => void;
  ready: boolean;
  timeRangeValid: boolean;
  isRunning: boolean;
  onClearResult: () => void;
  onRun: () => Promise<void>;
};

/** Only needed when the backend sets OPS_SIGNALS_API_TOKEN. Saved in this browser on blur; requests
 * made after that carry it. */
export function InteractiveAnalysisCard(props: InteractiveCardProps) {
  const [editingLabel, setEditingLabel] = useState(false);
  const [showBackend, setShowBackend] = useState(false);
  const [customOpen, setCustomOpen] = useState(false);
  const activePreset = customOpen ? null : presetFor(props.timeRange);
  const viaConnection = props.source === 'connection';
  const needsCluster = viaConnection && props.clusterOptions.length > 0;
  const missing = runBlockers(props);
  const { canEdit } = usePermissions();
  const canRun = props.ready && props.timeRangeValid && !props.isRunning && canEdit;

  return (
    <Card>
      <div style={{ ...styles.rowBetween, alignItems: 'flex-start', marginBottom: 6 }}>
        <div>
          <h2 style={{ margin: 0, color: '#73bf69' }}>Interactive Analysis</h2>
          <p style={{ ...styles.muted, margin: '5px 0 0' }}>Select a service, metric, and time range to investigate.</p>
        </div>
        <span style={styles.chip}>One metric per run</span>
      </div>

      <FormStep number={1} title="Data">
        <div style={formStyles.question}>Read metrics from</div>
        <div style={formStyles.sourceGrid}>
          <SourceOption
            show={props.connections.length > 0}
            checked={!viaConnection}
            label="Grafana data source"
            onSelect={() => props.setSource('grafana')}
          />
          <select
            aria-label="Data source"
            style={{ ...styles.input, ...(viaConnection ? formStyles.inactive : {}) }}
            disabled={viaConnection}
            value={props.selectedPrometheusUid}
            onChange={(event) => {
              props.setSelectedPrometheusUid(event.target.value);
              props.onClearResult();
            }}
          >
            <option value="">{props.prometheusDatasources.length ? 'Select Prometheus' : 'No Prometheus datasource'}</option>
            {props.prometheusDatasources.map((datasource) => (
              <option key={datasource.uid} value={datasource.uid}>{datasource.name}</option>
            ))}
          </select>
          {props.connections.length ? (
            <>
              <SourceOption show checked={viaConnection} label="Ops Signals connection" onSelect={() => props.setSource('connection')} />
              <div style={{ display: 'grid', gridTemplateColumns: needsCluster ? 'minmax(0, 1fr) minmax(0, 1fr)' : 'minmax(0, 1fr)', gap: 8 }}>
                <ConnectionPicker
                  compact
                  disabled={!viaConnection}
                  backendUrl={props.backendUrl}
                  connections={props.connections}
                  connectionId={props.connectionId}
                  onChange={props.setConnectionId}
                />
                {needsCluster ? (
                  <select aria-label="Cluster" style={styles.input} value={props.cluster} onChange={(event) => props.setCluster(event.target.value)}>
                    <option value="">Choose a cluster</option>
                    {props.clusterOptions.map((cluster) => (
                      <option key={cluster} value={cluster}>{cluster}</option>
                    ))}
                  </select>
                ) : null}
              </div>
            </>
          ) : null}
        </div>
        <div style={styles.helperText}>
          {viaConnection
            ? 'The Ops Signals backend reads it directly: one cluster per run, findings tagged with it, and one copy of HA-duplicated series. Use this for Mimir tenants and clusters.'
            : 'Grafana reads the data source and sends the numbers to Ops Signals.'}
        </div>
        {needsCluster ? (
          <div style={{ ...styles.helperText, ...(props.cluster ? {} : { color: '#ffb357' }) }}>
            This series is in {props.clusterOptions.length} clusters; one is analysed per run.{props.cluster ? '' : ' Choose one to run.'}
          </div>
        ) : null}
      </FormStep>

      <FormStep number={2} title="What">
        <div style={formStyles.whatGrid}>
          <div style={{ minWidth: 0 }}>
            <Field label="Service">
              <input
                style={styles.input}
                list="ops-signals-services"
                value={props.target.service}
                placeholder="Pick or type a service"
                onChange={(event) => props.setTarget((current) => ({ ...current, service: event.target.value }))}
              />
            </Field>
            <datalist id="ops-signals-services">
              {(viaConnection ? props.connectionServices : props.services).map((service) => (
                <option key={service} value={service} />
              ))}
            </datalist>
            {editingLabel || !props.serviceLabel ? (
              <>
                <div style={{ ...styles.row, gap: 8, marginTop: 8, flexWrap: 'nowrap' }}>
                  <span style={styles.helperText}>matched on label</span>
                  <input
                    aria-label="Service label"
                    style={{ ...styles.input, width: 140, minHeight: 28, padding: '3px 8px' }}
                    value={props.serviceLabel}
                    placeholder="service"
                    onChange={(event) => props.setServiceLabel(event.target.value)}
                  />
                  <button type="button" style={formStyles.link} disabled={!props.serviceLabel} onClick={() => setEditingLabel(false)}>done</button>
                </div>
                <div style={styles.helperText}>The label that names the service in your metrics. Usually "service"; some setups use "job" or "app".</div>
              </>
            ) : (
              <div style={styles.helperText}>
                matched on label <strong>{props.serviceLabel}</strong> &middot;{' '}
                <button type="button" aria-label="Change service label" style={formStyles.link} onClick={() => setEditingLabel(true)}>change</button>
              </div>
            )}
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto', gap: 8, alignItems: 'end' }}>
              <Field label="Metric">
                <input
                  style={styles.input}
                  list="ops-signals-metrics"
                  value={props.target.metric}
                  placeholder={props.metricMode === 'metric' ? 'Metric name' : 'PromQL expression'}
                  onChange={(event) => props.setTarget((current) => ({ ...current, metric: event.target.value }))}
                />
              </Field>
              <div role="group" aria-label="Metric or PromQL" style={formStyles.segment}>
                {([['metric', 'Metric'], ['promql', 'PromQL']] as const).map(([mode, label]) => (
                  <button
                    key={mode}
                    type="button"
                    aria-pressed={props.metricMode === mode}
                    style={{ ...formStyles.segmentButton, ...(props.metricMode === mode ? formStyles.segmentOn : {}) }}
                    onClick={() => props.setMetricMode(mode)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <datalist id="ops-signals-metrics">
              {(viaConnection ? props.connectionMetrics : props.metrics).map((metric) => (
                <option key={metric} value={metric} />
              ))}
            </datalist>
          </div>
        </div>
      </FormStep>

      <FormStep number={3} title="When">
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {timePresets.map((preset) => (
            <button
              key={preset.label}
              type="button"
              aria-pressed={activePreset === preset.hours}
              style={{ ...formStyles.preset, ...(activePreset === preset.hours ? formStyles.presetOn : {}) }}
              onClick={() => {
                setCustomOpen(false);
                props.applyPreset(preset.hours);
              }}
            >
              {preset.label}
            </button>
          ))}
          <button
            type="button"
            aria-pressed={customOpen}
            style={{ ...formStyles.preset, ...(customOpen ? formStyles.presetOn : {}) }}
            onClick={() => setCustomOpen((open) => !open)}
          >
            Custom…
          </button>
        </div>
        {customOpen ? (
          <div style={formStyles.customGrid}>
            <Field label="From">
              <input
                style={styles.input}
                type="datetime-local"
                value={props.timeFromInput}
                onChange={(event) => {
                  props.setTimeFromInput(event.target.value);
                  props.applyCustomRange(event.target.value, props.timeToInput);
                }}
              />
            </Field>
            <Field label="To">
              <input
                style={styles.input}
                type="datetime-local"
                value={props.timeToInput}
                onChange={(event) => {
                  props.setTimeToInput(event.target.value);
                  props.applyCustomRange(props.timeFromInput, event.target.value);
                }}
              />
            </Field>
          </div>
        ) : null}
        <div style={{ marginTop: 10, fontSize: 13 }}>
          {formatRange(props.timeRange)} <span style={styles.muted}>&middot; {formatRangeLength(props.timeRange)}{customOpen ? ' · applied as you change it' : ''}</span>
        </div>
      </FormStep>

      <div style={formStyles.footer}>
        <div style={styles.helperText}>
          <BackendLabel backendUrl={props.backendUrl} open={showBackend} onToggle={() => setShowBackend((open) => !open)} />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6 }}>
          <button
            type="button"
            style={canRun ? { ...styles.button, padding: '9px 22px' } : { ...styles.button, ...styles.buttonDisabled, padding: '9px 22px' }}
            onClick={props.onRun}
            disabled={!canRun}
          >
            {props.isRunning ? 'Running...' : `${canEdit ? '' : '🔒 '}Run Analysis`}
          </button>
          {!canEdit ? (
            <span style={{ fontSize: 12, color: '#ffb357' }}>{LOCK_REASONS.runAnalysis}</span>
          ) : !props.isRunning && missing.length ? <span style={{ fontSize: 12, color: '#ffb357' }}>{missing}</span> : null}
        </div>
      </div>
      {showBackend && !isGrafanaProxyUrl(props.backendUrl) ? (
        <div style={formStyles.backendPanel}>
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
              {(props.backendOptions ?? localBackendOptions).map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </Field>
          <ApiTokenField />
          <div style={{ ...styles.helperText, gridColumn: '1 / -1', marginTop: 0 }}>
            Admins set the default backend on the plugin's Configuration page. The token stays in this browser.
          </div>
        </div>
      ) : null}
    </Card>
  );
}

function FormStep({ number, title, children }: { number: number; title: string; children: React.ReactNode }) {
  return (
    <section aria-label={title} style={formStyles.step}>
      <div style={formStyles.stepTitle}>
        <span style={formStyles.stepNumber}>{number}</span>
        <span>{title.toUpperCase()}</span>
      </div>
      <div style={{ minWidth: 0 }}>{children}</div>
    </section>
  );
}

function SourceOption({ show, checked, label, onSelect }: { show: boolean; checked: boolean; label: string; onSelect: () => void }) {
  if (!show) return <div style={{ alignSelf: 'center' }}>{label}</div>;
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 9, cursor: 'pointer' }}>
      <input type="radio" name="ops-signals-read-from" checked={checked} onChange={onSelect} style={{ accentColor: '#5794f2', margin: 0 }} />
      {label}
    </label>
  );
}

/** What still stops a run, in form order, as one sentence (empty when the form is ready). */
function runBlockers(props: InteractiveCardProps): string {
  const items: string[] = [];
  if (props.source === 'connection') {
    if (!props.connectionId) items.push('choose a connection');
    if (props.clusterOptions.length && !props.cluster) items.push('choose a cluster');
  } else if (!props.selectedPrometheusUid) {
    items.push('choose a data source');
  }
  if (!props.target.service) items.push('enter a service');
  if (!props.target.metric) items.push(props.metricMode === 'promql' ? 'enter a PromQL expression' : 'enter a metric');
  if (!props.timeRangeValid) items.push('fix the time range');
  if (!items.length) return '';
  const sentence = items.length === 1 ? items[0] : `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
  return `${sentence.charAt(0).toUpperCase()}${sentence.slice(1)} to run.`;
}

/** The preset the range matches (by length, to the minute), or null for a custom range. */
function presetFor(range: InteractiveCardProps['timeRange']): number | null {
  const minutes = Math.round((range.to.getTime() - range.from.getTime()) / 60000);
  return timePresets.find((preset) => Math.round(preset.hours * 60) === minutes)?.hours ?? null;
}

function formatRange(range: InteractiveCardProps['timeRange']) {
  const sameDay = range.from.toDateString() === range.to.toDateString();
  const day = (value: Date) => value.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  const time = (value: Date) => value.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  return `${day(range.from)}, ${time(range.from)} → ${sameDay ? '' : `${day(range.to)}, `}${time(range.to)}`;
}

function formatRangeLength(range: InteractiveCardProps['timeRange']) {
  const minutes = Math.max(0, Math.round((range.to.getTime() - range.from.getTime()) / 60000));
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'}`;
  const hours = minutes / 60;
  if (hours < 48) return `${Number.isInteger(hours) ? hours : hours.toFixed(1)} hour${hours === 1 ? '' : 's'}`;
  return `${Math.round(hours / 24)} days`;
}

/** Why Autonomous Configure can't preview or save yet, as one sentence; empty when it can. */
export function autonomousConfigureBlocker(form: {
  selectedCategories: string[];
  allServices: boolean;
  selectedServices: string[];
  allNamespaces: boolean;
  selectedNamespaces: string[];
}): string {
  if (!form.selectedCategories.length) return 'Pick at least one category to watch.';
  if (!form.allServices && !form.selectedServices.length) return 'Pick at least one service, or choose All discovered.';
  if (!form.allNamespaces && !form.selectedNamespaces.length) return 'Pick at least one namespace, or choose All namespaces.';
  return '';
}

/**
 * The save button for Autonomous Configure, or null when there is none: a new setup saves only as a
 * schedule (running once happens from the preview); an existing schedule can also drop its schedule.
 */
export function autonomousSaveAction(input: { scheduleMode: 'run_once' | 'scheduled'; scheduleMinutes: number; editingPolicyName: string | null }): { label: string; hint: string } | null {
  const every = formatMinutes(input.scheduleMinutes);
  if (input.scheduleMode === 'scheduled') {
    return input.editingPolicyName
      ? { label: 'Save schedule', hint: `Saving updates ${input.editingPolicyName}; it runs every ${every}.` }
      : { label: 'Save & schedule', hint: `Preview first, or save now and it runs every ${every} without you.` };
  }
  return input.editingPolicyName
    ? { label: 'Save without schedule', hint: `Saving keeps ${input.editingPolicyName} but stops its scheduled runs.` }
    : null;
}

function formatMinutes(minutes: number) {
  return minutes % 60 === 0 ? `${minutes / 60}h` : `${minutes}m`;
}

/** "All discovered" or a picked list, shown as removable chips with a type-ahead to add more. */
export function ScopeChoice({ title, allLabel, pickLabel, all, setAll, options, selected, setSelected, emptyHint }: {
  title: string;
  allLabel: string;
  pickLabel: string;
  all: boolean;
  setAll: (value: boolean) => void;
  options: string[];
  selected: string[];
  setSelected: (value: string[]) => void;
  emptyHint: string;
}) {
  const [draft, setDraft] = useState('');
  const listId = `ops-signals-scope-${title.toLowerCase()}`;
  const remaining = options.filter((option) => !selected.includes(option));
  const add = (value: string) => {
    const next = value.trim();
    if (!next || selected.includes(next)) return;
    setSelected([...selected, next]);
    setDraft('');
  };
  return (
    <div role="radiogroup" aria-label={title} style={{ minWidth: 0 }}>
      <span style={styles.label}>{title}</span>
      <label style={{ ...formStyles.radio, marginBottom: 6 }}>
        <input type="radio" name={`${listId}-mode`} checked={all} onChange={() => setAll(true)} style={formStyles.radioInput} />
        {allLabel}
      </label>
      <label style={formStyles.radio}>
        <input type="radio" name={`${listId}-mode`} checked={!all} onChange={() => setAll(false)} style={formStyles.radioInput} />
        {pickLabel}
      </label>
      {!all ? (
        <div style={formStyles.chipBox}>
          {selected.map((value) => (
            <span key={value} style={{ ...styles.chip, ...formStyles.chipOn }}>
              {value}
              <button type="button" aria-label={`Remove ${value}`} style={formStyles.chipRemove} onClick={() => setSelected(selected.filter((item) => item !== value))}>✕</button>
            </span>
          ))}
          <input
            aria-label={`Add ${title.toLowerCase()}`}
            list={listId}
            value={draft}
            placeholder="+ add"
            style={formStyles.chipInput}
            onChange={(event) => {
              const value = event.target.value;
              // Picking from the suggestions adds it straight away; typing waits for Enter.
              if (remaining.includes(value)) add(value);
              else setDraft(value);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                add(draft);
              }
            }}
          />
          <datalist id={listId}>
            {remaining.slice(0, 200).map((option) => <option key={option} value={option} />)}
          </datalist>
        </div>
      ) : null}
      {!options.length ? <div style={styles.helperText}>{emptyHint}</div> : null}
    </div>
  );
}

function backendHost(url: string) {
  return url.replace(/^https?:\/\//, '').replace(/\/+$/, '') || 'not set';
}

/** "Backend: host · change", or, through Grafana, who set it: there is nothing for a person to change. */
function BackendLabel({ backendUrl, open, onToggle }: { backendUrl: string; open: boolean; onToggle: () => void }) {
  if (isGrafanaProxyUrl(backendUrl)) return <>Backend: through Grafana (set by your Grafana admin)</>;
  return (
    <>
      Backend: {backendHost(backendUrl)} &middot;{' '}
      <button type="button" aria-label={open ? 'Hide backend settings' : 'Change backend'} style={formStyles.link} onClick={onToggle}>{open ? 'hide' : 'change'}</button>
    </>
  );
}

const formStyles: Record<string, React.CSSProperties> = {
  step: { display: 'grid', gridTemplateColumns: '88px minmax(0, 1fr)', gap: 16, padding: '16px 0', borderTop: '1px solid rgba(204, 204, 220, 0.1)' },
  stepTitle: { display: 'flex', gap: 8, alignItems: 'center', alignSelf: 'start', paddingTop: 2, fontSize: 12, fontWeight: 600, letterSpacing: '0.06em', color: 'rgba(204, 204, 220, 0.66)' },
  stepNumber: { width: 20, height: 20, borderRadius: '50%', display: 'inline-grid', placeItems: 'center', background: 'rgba(87, 148, 242, 0.18)', color: '#8ab8ff', fontSize: 12 },
  question: { fontSize: 13, fontWeight: 500, marginBottom: 10 },
  sourceGrid: { display: 'grid', gridTemplateColumns: 'minmax(170px, 220px) minmax(0, 1fr)', gap: '10px 14px', alignItems: 'center', maxWidth: 920 },
  inactive: { opacity: 0.4 },
  whatGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 14, alignItems: 'start', maxWidth: 1100 },
  segment: { display: 'inline-flex', minHeight: 36, border: '1px solid rgba(204, 204, 220, 0.28)', borderRadius: 4, overflow: 'hidden' },
  segmentButton: { border: 0, background: 'transparent', color: 'rgba(204, 204, 220, 0.66)', padding: '0 12px', cursor: 'pointer', fontSize: 13 },
  segmentOn: { background: 'rgba(87, 148, 242, 0.2)', color: '#cfe0ff' },
  preset: { ...styles.chip, background: 'transparent', color: 'inherit', cursor: 'pointer' },
  presetOn: { border: '1px solid #5794f2', background: 'rgba(87, 148, 242, 0.16)', color: '#8ab8ff' },
  customGrid: { display: 'grid', gridTemplateColumns: 'repeat(2, minmax(180px, 240px))', gap: 14, marginTop: 12 },
  footer: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16, flexWrap: 'wrap', borderTop: '1px solid rgba(204, 204, 220, 0.1)', paddingTop: 16 },
  link: { border: 0, background: 'transparent', color: '#6e9fff', padding: 0, cursor: 'pointer', font: 'inherit' },
  editing: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, border: '1px solid rgba(87, 148, 242, 0.4)', background: 'rgba(87, 148, 242, 0.08)', borderRadius: 6, padding: '9px 12px', margin: '10px 0 4px', fontSize: 13 },
  scopeGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16, alignItems: 'start' },
  smallInput: { ...styles.input, width: 120, minHeight: 28, padding: '3px 8px' },
  radio: { display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13, whiteSpace: 'nowrap' },
  radioInput: { accentColor: '#5794f2', margin: 0 },
  chipBox: { display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginTop: 8, padding: 6, minHeight: 36, border: '1px solid rgba(204, 204, 220, 0.28)', borderRadius: 4, background: '#111217' },
  chipOn: { display: 'inline-flex', alignItems: 'center', gap: 6, borderColor: '#5794f2', background: 'rgba(87, 148, 242, 0.16)', color: '#8ab8ff' },
  chipRemove: { border: 0, background: 'transparent', color: 'inherit', padding: 0, cursor: 'pointer', opacity: 0.7, font: 'inherit' },
  chipInput: { flex: '1 0 80px', minWidth: 80, border: 0, background: 'transparent', color: 'inherit', outline: 'none', padding: '2px 4px' },
  // At most four per row, fewer when narrow.
  categoryGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(max(170px, calc((100% - 24px) / 4)), 1fr))', gap: 8 },
  category: { border: '1px solid rgba(204, 204, 220, 0.18)', borderRadius: 6, padding: '9px 11px', background: 'rgba(204, 204, 220, 0.04)', color: 'inherit', textAlign: 'left', cursor: 'pointer' },
  categoryOn: { border: '1px solid rgba(63, 207, 142, 0.65)', background: 'rgba(63, 207, 142, 0.1)' },
  customGrid3: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12, marginTop: 12 },
  whenGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16, alignItems: 'end', maxWidth: 1000 },
  backendPanel: { display: 'grid', gridTemplateColumns: 'minmax(260px, 1.4fr) minmax(200px, 1fr)', gap: 14, marginTop: 12, padding: 14, border: '1px solid rgba(204, 204, 220, 0.2)', borderRadius: 6, maxWidth: 860 },
};

function AutonomousAnalysisView({
  backendUrl,
  setBackendUrl,
  backendOptions,
  selectedPrometheusUid,
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
  connections,
  connectionId,
  setConnectionId,
  clusterOptions,
  clusterLabel,
  allClusters,
  setAllClusters,
  selectedClusters,
  setSelectedClusters,
  source,
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
  backendOptions: BackendOption[];
  selectedPrometheusUid: string;
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
  /** Backend Prometheus connections (one per Mimir tenant); a picker appears with two or more. */
  connections: PrometheusConnection[];
  connectionId: string | null;
  setConnectionId: (value: string | null) => void;
  /** Clusters behind the connection; a picker appears with two or more. */
  clusterOptions: string[];
  /** The label that tells clusters apart on this connection; null when turned off. */
  clusterLabel: string | null;
  allClusters: boolean;
  setAllClusters: (value: boolean) => void;
  selectedClusters: string[];
  setSelectedClusters: (value: string[]) => void;
  /** Connection and clusters as they go into a plan request. */
  source: { connectionId?: string; allClusters: boolean; selectedClusters: string[] };
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
  caseError: string;
  isCreatingCase: boolean;
  askState: AutonomousAskState;
  findingsLookupState: AutonomousFindingsLookupState;
  onRetryOverview: () => void;
  onBackToConfigure: () => void;
  onInvestigateInteractive: (finding: Finding) => void;
  onOpenInvestigation: (finding: Finding, mode: 'investigate' | 'evidence') => void;
  onCloseInvestigation: () => void;
  /** Resolves to the case id (new, or the finding's existing case), or null when it failed. */
  onCreateCase: (finding: Finding) => Promise<number | null>;
  onPreview: () => Promise<void>;
  onPreviewPolicy: (policy: AutonomousPolicy) => Promise<void>;
  onRunOnce: () => Promise<void>;
}) {
  const [previewStatusFilter, setPreviewStatusFilter] = useState<'all' | 'planned' | 'excluded'>('all');
  // Several clusters behind one Mimir or Thanos: the overview can look at one at a time.
  const [clusterFilter, setClusterFilter] = useState<string | null>(null);
  const clusters = useMemo(() => findingClusters(findings), [findings]);
  const { cluster: activeCluster, findings: clusterFindings } = useMemo(() => findingsInCluster(findings, clusterFilter), [findings, clusterFilter]);
  // One service at a time: findings, behavior findings and cases all follow it, so every panel on
  // the overview is about that service. Counts follow the cluster filter.
  const [serviceFilter, setServiceFilterState] = useState<string | null>(() => readServiceParam());
  const setServiceFilter = (service: string | null) => {
    setServiceFilterState(service);
    writeServiceParam(service);
  };
  const findingServices = useMemo(() => serviceOptions(clusterFindings, serviceFilter), [clusterFindings, serviceFilter]);
  const serviceFindings = useMemo(() => inService(clusterFindings, serviceFilter), [clusterFindings, serviceFilter]);
  const serviceBehaviors = useMemo(() => inService(behaviorFindings, serviceFilter), [behaviorFindings, serviceFilter]);
  const serviceCasesOnly = useMemo(() => casesInService(cases, serviceFilter), [cases, serviceFilter]);
  const [previewCategoryFilter, setPreviewCategoryFilter] = useState<string>('all');
  const [previewConceptFilter, setPreviewConceptFilter] = useState<string>('all');
  const [expandedPreviewMetric, setExpandedPreviewMetric] = useState<string | null>(null);

  // Scheduled-policy state: local to this view, same as the preview filters above - fetched
  // straight from the backend rather than prop-drilled through PluginApp, since it doesn't need
  // to be shared with any sibling view.
  const [activePolicy, setActivePolicy] = useState<AutonomousPolicy | null>(null);
  const { canEdit } = usePermissions();
  const [isLoadingPolicy, setIsLoadingPolicy] = useState(false);
  // Whether the first look for a saved schedule has finished: until then neither the schedule card nor
  // the form is shown, so the form doesn't flash and then turn into the card.
  const [policyChecked, setPolicyChecked] = useState(false);
  const [policyLoadError, setPolicyLoadError] = useState('');
  const [isEditingSchedule, setIsEditingSchedule] = useState(false);
  const [isSavingSchedule, setIsSavingSchedule] = useState(false);
  const [isTogglingSchedule, setIsTogglingSchedule] = useState(false);
  const [scheduleError, setScheduleError] = useState('');
  const [scheduleMode, setScheduleMode] = useState<'run_once' | 'scheduled'>('run_once');
  const [scheduleMinutes, setScheduleMinutes] = useState(30);
  const [forceOverview, setForceOverview] = useState(false);
  const [showScopeLabels, setShowScopeLabels] = useState(false);
  const [showLimit, setShowLimit] = useState(false);
  const [showBackend, setShowBackend] = useState(false);

  useEffect(() => {
    let active = true;
    if (!backendUrl) return;
    setIsLoadingPolicy(true);
    setPolicyChecked(false);
    setPolicyLoadError('');
    listAutonomousPolicies(backendUrl)
      .then((policies) => {
        if (active) setActivePolicy(policies[0] ?? null);
      })
      .catch(() => {
        if (active) setPolicyLoadError('Could not load your scheduled policy. Your schedule may still be running - this is a fetch problem, not a sign it was removed.');
      })
      .finally(() => {
        if (!active) return;
        setIsLoadingPolicy(false);
        setPolicyChecked(true);
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
        ...source,
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
        ...(request.connection_id ? { connection_id: request.connection_id } : {}),
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
    // First: changing the connection clears the service, namespace and cluster picks set below.
    setConnectionId(policy.connection_id ?? null);
    setEnvironment(policy.scope.environment ?? 'production');
    setServiceLabel(policy.scope.service_label);
    setNamespaceLabel(policy.scope.namespace_label);
    setEnvironmentLabel(policy.scope.environment_label);
    setAllServices(policy.scope.all_services);
    setSelectedServices(policy.scope.services);
    setAllNamespaces(policy.scope.all_namespaces);
    setSelectedNamespaces(policy.scope.namespaces);
    setAllClusters(policy.scope.all_clusters ?? true);
    setSelectedClusters(policy.scope.clusters ?? []);
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
    findings: serviceFindings,
    cases: serviceCasesOnly,
    analysisRuns: runs,
    behaviorFindings: serviceBehaviors,
    policyRuns,
    previewResult,
    runResult,
    findingHref: () => '#top-findings',
    caseHref: (caseItem) => `#case-${caseItem.id}`,
  });
  const previewRows = filterPreviewRows(previewResult?.items ?? [], previewStatusFilter, previewCategoryFilter, previewConceptFilter);
  // The backend reads its own connection for autonomous runs; the Grafana data source plays no part.
  const configureBlocker = autonomousConfigureBlocker({ selectedCategories, allServices, selectedServices, allNamespaces, selectedNamespaces });
  const canPreview = Boolean(backendUrl && !configureBlocker);
  const saveAction = autonomousSaveAction({ scheduleMode, scheduleMinutes, editingPolicyName: activePolicy?.name ?? null });
  const showSave = saveAction !== null;
  const canSave = !configureBlocker && !isSavingSchedule && canEdit;
  const saveLabel = saveAction?.label ?? '';
  const saveHint = saveAction?.hint ?? 'Preview first, then run the planned metrics once from the preview.';
  const canRunOnce = Boolean(previewResult?.planned_jobs && !isRunningOnce && canEdit);
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
                {scheduleAuthorLine(activePolicy) ? <p style={{ ...styles.muted, margin: '4px 0 0', fontSize: 12 }}>{scheduleAuthorLine(activePolicy)}</p> : null}
                <p style={{ ...styles.muted, margin: '5px 0 0' }}>
                  {activePolicy.monitoring_selection.categories.join(', ')} &middot; every {activePolicy.schedule_minutes ? `${activePolicy.schedule_minutes}m` : 'n/a'}
                </p>
                {connections.length > 1 || (activePolicy.scope.all_clusters === false && activePolicy.scope.clusters?.length) ? (
                  <p style={{ ...styles.muted, margin: '3px 0 0' }}>
                    {[
                      connections.length > 1 ? (connectionName(connections, activePolicy.connection_id ?? 'default') ?? activePolicy.connection_id) : null,
                      activePolicy.scope.all_clusters === false && activePolicy.scope.clusters?.length ? `clusters ${activePolicy.scope.clusters.join(', ')}` : null,
                    ].filter(Boolean).join(' · ')}
                  </p>
                ) : null}
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button type="button" style={canEdit ? styles.button : { ...styles.button, ...styles.buttonDisabled }} disabled={!canEdit} title={canEdit ? undefined : LOCK_REASONS.schedule} onClick={handleEditSchedule}>{canEdit ? '' : '🔒 '}Edit</button>
                {activePolicy.enabled ? (
                  <button
                    type="button"
                    style={{ ...styles.button, background: 'rgba(204, 204, 220, 0.08)', border: '1px solid rgba(204, 204, 220, 0.28)', ...(canEdit ? {} : styles.buttonDisabled) }}
                    disabled={isTogglingSchedule || !canEdit}
                    onClick={handlePauseSchedule}
                    title={canEdit ? 'Stop scheduled runs. The schedule is kept and can be resumed.' : LOCK_REASONS.schedule}
                  >
                    {isTogglingSchedule ? 'Pausing...' : `${canEdit ? '' : '🔒 '}Pause`}
                  </button>
                ) : (
                  <button type="button" style={canEdit ? styles.button : { ...styles.button, ...styles.buttonDisabled }} disabled={isTogglingSchedule || !canEdit} title={canEdit ? undefined : LOCK_REASONS.schedule} onClick={handleResumeSchedule}>
                    {isTogglingSchedule ? 'Resuming...' : `${canEdit ? '' : '🔒 '}Resume`}
                  </button>
                )}
              </div>
            </div>
            {canEdit ? null : <LockReason style={{ marginTop: -6, marginBottom: 10 }}>{LOCK_REASONS.schedule}</LockReason>}
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
        ) : !policyChecked && !isEditingSchedule ? (
          <p role="status" style={{ ...styles.muted, margin: 0 }}>Loading your schedule…</p>
        ) : (
        <>
        <div style={{ ...styles.rowBetween, alignItems: 'flex-start', marginBottom: 6 }}>
          <div>
            <h2 style={{ margin: 0, color: '#3fcf8e' }}>Configure</h2>
            <p style={{ ...styles.muted, margin: '5px 0 0' }}>
              Choose what to watch, preview the planned metrics, then run once or save a schedule.
            </p>
          </div>
        </div>
        {activePolicy && isEditingSchedule ? (
          <div style={formStyles.editing}>
            <span>
              Editing <strong>{activePolicy.name}</strong>
              {activePolicy.schedule_minutes ? ` · every ${formatMinutes(activePolicy.schedule_minutes)}` : ''} · changes apply from the next run
            </span>
            <button type="button" style={formStyles.link} onClick={() => setIsEditingSchedule(false)}>Cancel edit</button>
          </div>
        ) : null}

        <FormStep number={1} title="Data">
          <div style={formStyles.question}>Read metrics from</div>
          {connections.length ? (
            <div style={{ maxWidth: 520 }}>
              <ConnectionPicker compact backendUrl={backendUrl} connections={connections} connectionId={connectionId} onChange={setConnectionId} />
            </div>
          ) : (
            <div>The backend's default Prometheus</div>
          )}
          <div style={styles.helperText}>
            The Ops Signals backend reads this connection on every run, so the analysis keeps working when Grafana isn't open.
          </div>
          <div style={{ marginTop: 12, maxWidth: 520 }}>
            <ClustersField
              clusterOptions={clusterOptions}
              clusterLabel={clusterLabel}
              allClusters={allClusters}
              setAllClusters={setAllClusters}
              selectedClusters={selectedClusters}
              setSelectedClusters={setSelectedClusters}
            />
          </div>
        </FormStep>

        <FormStep number={2} title="Scope">
          <div style={formStyles.scopeGrid}>
            <Field label="Environment">
              <select style={styles.input} value={environment} onChange={(event) => setEnvironment(event.target.value)}>
                <option value="production">Production</option>
                <option value="staging">Staging</option>
                <option value="all">All environments</option>
              </select>
            </Field>
            <ScopeChoice
              title="Services"
              allLabel={`All discovered${services.length ? ` (${services.length})` : ''}`}
              pickLabel="Pick services"
              all={allServices}
              setAll={setAllServices}
              options={services}
              selected={selectedServices}
              setSelected={setSelectedServices}
              emptyHint="No services found yet. Check the service label below."
            />
            <ScopeChoice
              title="Namespaces"
              allLabel="All namespaces"
              pickLabel="Pick namespaces"
              all={allNamespaces}
              setAll={setAllNamespaces}
              options={namespaces}
              selected={selectedNamespaces}
              setSelected={setSelectedNamespaces}
              emptyHint="No namespaces found. Keep All, or check the namespace label below."
            />
          </div>
          {showScopeLabels ? (
            <div style={{ ...styles.row, gap: 10, marginTop: 10, fontSize: 12 }}>
              <span style={styles.muted}>matched on labels</span>
              {([
                ['environment', environmentLabel, setEnvironmentLabel],
                ['service', serviceLabel, setServiceLabel],
                ['namespace', namespaceLabel, setNamespaceLabel],
              ] as const).map(([name, value, setValue]) => (
                <label key={name} style={{ ...styles.row, gap: 6 }}>
                  <span style={styles.muted}>{name}</span>
                  <input aria-label={`${name[0].toUpperCase()}${name.slice(1)} label`} style={formStyles.smallInput} value={value} onChange={(event) => setValue(event.target.value)} />
                </label>
              ))}
              <button type="button" style={formStyles.link} onClick={() => setShowScopeLabels(false)}>done</button>
            </div>
          ) : (
            <div style={styles.helperText}>
              matched on labels <strong>{environmentLabel}</strong> &middot; <strong>{serviceLabel}</strong> &middot; <strong>{namespaceLabel}</strong> &middot;{' '}
              <button type="button" aria-label="Change scope labels" style={formStyles.link} onClick={() => setShowScopeLabels(true)}>change</button>
            </div>
          )}
        </FormStep>

        <FormStep number={3} title="Watch">
          <div style={formStyles.categoryGrid}>
            {monitorCategories.map((item) => {
              const on = selectedCategories.includes(item.id);
              return (
                <button key={item.id} type="button" aria-pressed={on} onClick={() => toggleCategory(item.id)} style={{ ...formStyles.category, ...(on ? formStyles.categoryOn : {}) }}>
                  <span style={{ ...styles.rowBetween, gap: 8, flexWrap: 'nowrap' }}>
                    <strong style={{ fontWeight: 500 }}>{item.title}</strong>
                    {on ? <span style={{ color: '#3fcf8e' }}>✓</span> : null}
                  </span>
                  <span style={{ ...styles.helperText, display: 'block', marginTop: 2 }}>{item.detail}</span>
                </button>
              );
            })}
          </div>
          {selectedCategories.includes('custom') ? (
            <>
              <div style={formStyles.customGrid3}>
                <Field label="Metric names">
                  <input style={styles.input} value={customExplicitMetrics} onChange={(event) => setCustomExplicitMetrics(event.target.value)} placeholder="http_requests_total, node_cpu_seconds_total" />
                </Field>
                <Field label="Include patterns">
                  <input style={styles.input} value={customIncludePatterns} onChange={(event) => setCustomIncludePatterns(event.target.value)} placeholder=".*latency.*, custom_metric_.*" />
                </Field>
                <Field label="Exclude patterns">
                  <input style={styles.input} value={customExcludePatterns} onChange={(event) => setCustomExcludePatterns(event.target.value)} placeholder=".*_bucket" />
                </Field>
              </div>
              <div style={styles.helperText}>Comma-separated. Patterns are regular expressions on the metric name.</div>
            </>
          ) : null}
        </FormStep>

        <FormStep number={4} title="When">
          <div style={formStyles.whenGrid}>
            <div>
              <span style={styles.label}>Run</span>
              <div role="radiogroup" aria-label="Run" style={{ ...styles.row, gap: 16, minHeight: 36, flexWrap: 'nowrap' }}>
                <label style={formStyles.radio}>
                  <input type="radio" name="ops-signals-run-mode" checked={scheduleMode === 'run_once'} onChange={() => setScheduleMode('run_once')} style={formStyles.radioInput} />
                  Once, now
                </label>
                <label style={formStyles.radio}>
                  <input type="radio" name="ops-signals-run-mode" checked={scheduleMode === 'scheduled'} onChange={() => setScheduleMode('scheduled')} style={formStyles.radioInput} />
                  Every
                </label>
                <select
                  aria-label="Run every"
                  style={{ ...styles.input, width: 96, ...(scheduleMode === 'scheduled' ? {} : formStyles.inactive) }}
                  disabled={scheduleMode !== 'scheduled'}
                  value={scheduleMinutes}
                  onChange={(event) => setScheduleMinutes(Number(event.target.value))}
                >
                  <option value={5}>5m</option>
                  <option value={15}>15m</option>
                  <option value={30}>30m</option>
                  <option value={60}>1h</option>
                  <option value={360}>6h</option>
                </select>
              </div>
            </div>
            <Field label="Look back">
              <select style={styles.input} value={analysisWindow} onChange={(event) => setAnalysisWindow(event.target.value)}>
                <option value="30m">30m</option>
                <option value="1h">1h</option>
                <option value="6h">6h</option>
                <option value="24h">24h</option>
                <option value="7d">7d</option>
              </select>
            </Field>
            <Field label="Resolution">
              <select style={styles.input} value={executionInterval} onChange={(event) => setExecutionInterval(event.target.value)}>
                <option value="30s">30s</option>
                <option value="1m">1m</option>
                <option value="5m">5m</option>
                <option value="10m">10m</option>
              </select>
            </Field>
          </div>
          {showLimit ? (
            <div style={{ ...styles.row, gap: 8, marginTop: 10, fontSize: 12 }}>
              <span style={styles.muted}>Up to</span>
              <input aria-label="Max metrics per run" style={{ ...formStyles.smallInput, width: 90 }} type="number" min={1} max={5000} value={maxMetricsPerRun} onChange={(event) => setMaxMetricsPerRun(event.target.value)} />
              <span style={styles.muted}>metrics per run</span>
              <button type="button" style={formStyles.link} onClick={() => setShowLimit(false)}>done</button>
            </div>
          ) : (
            <div style={styles.helperText}>
              Up to <strong>{maxMetricsPerRun || '0'}</strong> metrics per run &middot;{' '}
              <button type="button" aria-label="Change metrics per run" style={formStyles.link} onClick={() => setShowLimit(true)}>change</button>
            </div>
          )}
        </FormStep>

        {scheduleError ? <div style={{ ...styles.alert, marginBottom: 12 }}>{scheduleError}</div> : null}
        <div style={formStyles.footer}>
          <div style={styles.helperText}>
            <BackendLabel backendUrl={backendUrl} open={showBackend} onToggle={() => setShowBackend((open) => !open)} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6 }}>
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="button" style={canPreview && !isPreviewing ? styles.button : { ...styles.button, ...styles.buttonDisabled }} disabled={!canPreview || isPreviewing} onClick={onPreview}>
                {isPreviewing ? 'Building preview...' : 'Preview metric plan'}
              </button>
              {showSave ? (
                <button
                  type="button"
                  style={canSave ? { ...styles.button, background: '#3fcf8e', color: '#08130e' } : { ...styles.button, ...styles.buttonDisabled }}
                  disabled={!canSave}
                  onClick={handleSaveSchedule}
                >
                  {isSavingSchedule ? 'Saving...' : saveLabel}
                </button>
              ) : null}
            </div>
            {configureBlocker ? (
              <span style={{ fontSize: 12, color: '#ffb357' }}>{configureBlocker}</span>
            ) : !canEdit ? (
              <span style={{ fontSize: 12, color: '#ffb357' }}>{LOCK_REASONS.saveOrRun}</span>
            ) : (
              <span style={styles.helperText}>{saveHint}</span>
            )}
          </div>
        </div>
        {showBackend && !isGrafanaProxyUrl(backendUrl) ? (
          <div style={formStyles.backendPanel}>
            <Field label="Ops Signals backend">
              <select style={styles.input} value={backendUrl} onChange={(event) => setBackendUrl(event.target.value)}>
                {backendOptions.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </Field>
            <ApiTokenField />
            <div style={{ ...styles.helperText, gridColumn: '1 / -1', marginTop: 0 }}>
              Admins set the default backend on the plugin's Configuration page. The token stays in this browser.
            </div>
          </div>
        ) : null}
        </>
        )}
      </Card>
      ) : null}

      {uiStage === 'preview_loading' ? <PreviewLoadingPanel /> : null}
      {uiStage === 'preview_error' ? <PreviewErrorPanel onRetry={onPreview} onBack={handleBackToConfigure} /> : null}
      {uiStage === 'preview_ready' ? (
        <PreviewPlanPanel
          result={previewResult}
          connectionLabel={connectionName(connections, connectionId)}
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
          findings={serviceFindings}
          clusters={clusters}
          clusterFilter={activeCluster}
          onClusterFilter={setClusterFilter}
          services={findingServices}
          serviceFilter={serviceFilter}
          onServiceFilter={setServiceFilter}
          behaviorFindings={serviceBehaviors}
          state={dashboardState}
          endpointErrors={endpointErrors}
          onRetry={onRetryOverview}
          investigationFinding={investigationFinding}
          investigationMode={investigationMode}
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
            sourceLabel: `Prometheus / ${connectionName(connections, connectionId) ?? "the backend's default connection"}`,
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

export function GrafanaAutonomousOverview({
  backendUrl,
  data,
  findings,
  clusters = [],
  clusterFilter = null,
  onClusterFilter,
  services = [],
  serviceFilter = null,
  onServiceFilter,
  behaviorFindings,
  state,
  context,
  endpointErrors,
  onRetry,
  investigationFinding,
  investigationMode,
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
  /** Clusters in the window's findings; chips to look at one appear when there are two or more. */
  clusters?: string[];
  clusterFilter?: string | null;
  onClusterFilter?: (cluster: string | null) => void;
  /** Services in the window's findings; the select appears when there are two or more. */
  services?: ServiceOption[];
  serviceFilter?: string | null;
  onServiceFilter?: (service: string | null) => void;
  behaviorFindings: BehaviorFinding[];
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
  caseError: string;
  isCreatingCase: boolean;
  askState: AutonomousAskState;
  findingsLookupState: AutonomousFindingsLookupState;
  onOpenInvestigation: (finding: Finding, mode: 'investigate' | 'evidence') => void;
  onInvestigateInteractive: (finding: Finding) => void;
  onCloseInvestigation: () => void;
  onCreateCase: (finding: Finding) => Promise<number | null>;
  onEnableCategory?: (category: MonitoringCategory) => void;
  onPreviewNow?: () => void;
  isPreviewingNow?: boolean;
  previewNowError?: string;
}) {
  const { canEdit } = usePermissions();
  const servicePriorities = buildServicePriorities(data.topFindings);
  const primaryService = servicePriorities[0] ?? null;
  const primaryServiceName = primaryService?.service ?? null;
  const symptoms = useMemo(() => (primaryServiceName ? serviceSymptoms(findings, primaryServiceName) : []), [findings, primaryServiceName]);
  const triage = useMemo(() => triageSymptoms(symptoms), [symptoms]);
  // Behavior matches each finding is part of: same service, one of the rule's metrics, same run.
  const patternsOfFinding = useMemo(() => patternsByFinding(behaviorFindings, findings), [behaviorFindings, findings]);
  const patternsOf = (symptom: ServiceSymptom): BehaviorFinding[] => {
    const seen = new Map<number, BehaviorFinding>();
    for (const run of symptom.runs) for (const behavior of patternsOfFinding.get(run.id ?? -1) ?? []) seen.set(behavior.id, behavior);
    return [...seen.values()];
  };
  const [behaviorsShown, setBehaviorsShown] = useSectionShown('behavior-findings');
  // A "Part of" chip opens Behavior findings if it was hidden, then scrolls to the match.
  const showBehavior = (id: number) => {
    if (!behaviorsShown) setBehaviorsShown(true);
    window.setTimeout(() => document.getElementById(behaviorAnchor(id))?.scrollIntoView?.({ behavior: 'smooth', block: 'center' }), 0);
  };
  const linkedBehaviorIds = useMemo(
    () => [...new Set(triage.attention.flatMap((row) => row.lead.runs.flatMap((run) => (patternsOfFinding.get(run.id ?? -1) ?? []).map((behavior) => behavior.id))))],
    [triage, patternsOfFinding],
  );
  const [showAllSymptoms, setShowAllSymptoms] = useState(false);
  // Finding id -> case id: the service's cases, plus cases opened on this page since.
  const [serviceCases, setServiceCases] = useState<Map<number, number>>(new Map());
  // Who opened each case and when, for "Created by admin · 3h ago" under its button.
  const [caseAuthors, setCaseAuthors] = useState<Map<number, { by?: string | null; at?: string | null }>>(new Map());
  const noteCaseAuthors = (cases: Array<Pick<GrafanaCase, 'id' | 'created_by' | 'created_at'>>) =>
    setCaseAuthors((current) => {
      const next = new Map(current);
      for (const item of cases) next.set(item.id, { by: item.created_by, at: item.created_at });
      return next;
    });
  const [createdCases, setCreatedCases] = useState<Map<number, number>>(new Map());
  const [drawerCase, setDrawerCase] = useState<GrafanaCase | null>(null);
  const [drawerSource, setDrawerSource] = useState<string | null>(null);
  const [drawerChanged, setDrawerChanged] = useState(false);
  const [connections, setConnections] = useState<PrometheusConnection[]>([]);

  useEffect(() => {
    if (!backendUrl) return;
    let active = true;
    listPrometheusConnections(backendUrl)
      .then((response) => { if (active) setConnections(response.connections); })
      .catch(() => undefined);
    return () => { active = false; };
  }, [backendUrl]);
  const [openCaseError, setOpenCaseError] = useState('');

  useEffect(() => {
    if (!backendUrl || !primaryServiceName) return;
    let active = true;
    listCases(backendUrl, { service: primaryServiceName, limit: 200 })
      .then((cases) => {
        if (!active) return;
        setServiceCases(caseIdsByFinding(cases));
        noteCaseAuthors(cases);
      })
      .catch(() => undefined);
    return () => { active = false; };
  }, [backendUrl, primaryServiceName]);

  // The finding panel sits right under the top card; bring it into view when a finding is opened.
  const investigationId = investigationFinding?.id;
  useEffect(() => {
    if (investigationId === undefined) return;
    document.getElementById('autonomous-investigation')?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' });
  }, [investigationId]);

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

  // The card is about the lead service, so its chips and default finding are that service's own top
  // finding - not the top across services, which can be on one ranked after it (no service label).
  const topFinding = primaryService?.symptoms.reduce((best, item) => (item.importance > best.importance ? item : best)) ?? data.topFindings[0] ?? null;
  const topRawFinding = topFinding ? matchingFinding(findings, topFinding) : null;
  const hasFindings = data.topFindings.length > 0;
  const disabledActionStyle = {
    ...styles.buttonDisabled,
    border: '1px solid rgba(204, 204, 220, 0.14)',
    opacity: 0.72,
  };
  const caseByFinding = new Map([...serviceCases, ...createdCases]);
  const symptomCount = symptoms.length;
  const symptomMetrics = Array.from(new Set(symptoms.map((symptom) => symptom.finding.metric_name)));
  const attentionCount = triage.attention.length;
  const leadSymptom = triageOrder(triage)[0] ?? null;
  const leadChange = leadSymptom ? symptomChange(leadSymptom.finding) : null;
  // The symptom the buttons act on: the one open below, else the worst one that needs attention.
  const selectedSymptom = symptomOf(symptoms, investigationFinding) ?? leadSymptom;
  const selectedFinding = selectedSymptom?.finding ?? topRawFinding;
  const selectedCaseId = selectedSymptom ? caseForSymptom(selectedSymptom, caseByFinding) : null;
  const panelSymptom = symptomOf(symptoms, investigationFinding);
  const panelCaseId = panelSymptom
    ? caseForSymptom(panelSymptom, caseByFinding)
    : investigationFinding?.id !== undefined ? caseByFinding.get(investigationFinding.id) ?? null : null;
  const headline = primaryService
    ? attentionCount > 1
      ? `Likely incident candidate: ${serviceLabel(primaryService.service)}`
      : `Important finding detected: ${serviceLabel(primaryService.service)}`
    : 'No important findings detected';
  const summaryText = primaryService && leadSymptom
    ? attentionCount
      ? `${attentionCount} metric${attentionCount === 1 ? '' : 's'} on ${serviceLabel(primaryService.service)} need${attentionCount === 1 ? 's' : ''} attention. Primary concern: ${leadSymptom.finding.metric_name}${leadChange ? ` ${leadChange.text}${leadChange.percent ? ` (${leadChange.percent})` : ''}` : ''}.`
      : `Nothing on ${serviceLabel(primaryService.service)} needs attention: ${triage.data.length ? `${triage.data.length} data problem${triage.data.length === 1 ? '' : 's'}` : ''}${triage.data.length && triage.background.length ? ' and ' : ''}${triage.background.length ? `${triage.background.length} background signal${triage.background.length === 1 ? '' : 's'}` : ''}.`
    : `${formatNullableCount(data.summary.executed)} metric${data.summary.executed === 1 ? '' : 's'} executed with no current-run findings.`;
  const roleLabel = (symptom: ServiceSymptom) => ({ attention: 'Needs attention', data: 'Data problem', background: 'Background signal' })[symptomRole(symptom.finding)];
  const sourceOf = (finding: Finding) => findingSource(finding, connections);

  /** Opens the finding's case in the drawer, creating it first when there is none. */
  async function openOrCreateCase(finding: Finding, knownCaseId: number | null) {
    setOpenCaseError('');
    let caseId = knownCaseId;
    if (caseId === null) {
      onOpenInvestigation(finding, 'investigate');
      caseId = await onCreateCase(finding);
      if (caseId === null) return;
      if (finding.id !== undefined) {
        const findingId = finding.id;
        const created = caseId;
        setCreatedCases((current) => new Map(current).set(findingId, created));
      }
    }
    try {
      const opened = await getCase(backendUrl, caseId);
      setDrawerCase(opened);
      noteCaseAuthors([opened]);
      setDrawerSource(findingSource(finding, connections));
      setDrawerChanged(false);
    } catch {
      setOpenCaseError(`Could not open case #${caseId}. Check the backend connection and retry.`);
    }
  }

  function closeDrawer() {
    setDrawerCase(null);
    if (drawerChanged) onRetry();
  }

  const caseButton = (finding: Finding | null, caseId: number | null, compact = false) => {
    if (!finding) return null;
    const size = compact ? { padding: '4px 10px', fontSize: 12, whiteSpace: 'nowrap' as const } : {};
    if (isCreatingCase) return <button type="button" style={{ ...styles.button, ...size, ...disabledActionStyle }} disabled>Creating case...</button>;
    if (caseId !== null) {
      const author = caseAuthors.get(caseId);
      const created = author?.by ? `Created ${byLine(author.by, author.at)}` : '';
      const button = (
        <button
          type="button"
          style={{ ...styles.button, ...size, background: 'rgba(63, 207, 142, 0.14)', border: '1px solid rgba(63, 207, 142, 0.5)', color: '#b9f5d8' }}
          title={`Open this symptom's case: investigation, root cause, resolution and publishing.${created ? ` ${created}.` : ''}`}
          onClick={() => openOrCreateCase(finding, caseId)}
        >
          Open case #{caseId} ▸
        </button>
      );
      if (compact || !created) return button;
      return (
        <span style={{ display: 'inline-flex', flexDirection: 'column', gap: 4, alignItems: 'flex-start' }}>
          {button}
          <span style={{ ...styles.helperText, marginTop: 0 }}>{created}</span>
        </span>
      );
    }
    const createButton = (
      <button
        type="button"
        style={{ ...styles.button, ...size, background: 'rgba(204, 204, 220, 0.12)', border: '1px solid rgba(204, 204, 220, 0.22)', ...(finding.id ? {} : disabledActionStyle) }}
        disabled={!finding.id || !canEdit}
        title={!canEdit ? LOCK_REASONS.createCase : finding.id ? 'Open a case for this symptom and start the investigation.' : 'This finding has not been persisted yet.'}
        onClick={() => openOrCreateCase(finding, null)}
      >
        {canEdit ? '' : '🔒 '}Create case
      </button>
    );
    if (canEdit || compact) return createButton;
    return (
      <span style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'flex-start' }}>
        {createButton}
        <LockReason>{LOCK_REASONS.createCase}</LockReason>
      </span>
    );
  };

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
      {onServiceFilter && showServiceFilter(services, serviceFilter) ? (
        <div style={{ ...styles.row, gap: 6 }}>
          <label htmlFor="overview-service-filter" style={{ ...styles.helperText, margin: 0 }}>Service</label>
          <select
            id="overview-service-filter"
            style={{ ...styles.input, width: 'auto', minWidth: 200 }}
            value={serviceFilter ?? ''}
            onChange={(event) => onServiceFilter(event.target.value || null)}
          >
            <option value="">All services ({services.reduce((total, item) => total + item.count, 0)})</option>
            {services.map((item) => <option key={item.key} value={item.key}>{item.label} ({item.count})</option>)}
          </select>
          {serviceFilter ? (
            <button type="button" style={{ ...styles.chip, cursor: 'pointer', background: 'transparent', color: 'inherit' }} onClick={() => onServiceFilter(null)}>
              Show all services
            </button>
          ) : null}
        </div>
      ) : null}
      {clusters.length > 1 && onClusterFilter ? (
        <div role="group" aria-label="Cluster" style={{ ...styles.row, gap: 6 }}>
          <span style={{ ...styles.helperText, margin: 0 }}>Cluster</span>
          {[null, ...clusters].map((cluster) => (
            <button
              key={cluster ?? 'all'}
              type="button"
              aria-pressed={clusterFilter === cluster}
              onClick={() => onClusterFilter(cluster)}
              style={{ ...styles.chip, background: clusterFilter === cluster ? '#5794f2' : 'transparent', color: clusterFilter === cluster ? '#fff' : 'inherit', cursor: 'pointer', ...(clusterFilter === cluster ? { border: '1px solid #5794f2' } : {}) }}
            >
              {cluster ?? 'All clusters'}
            </button>
          ))}
          <span style={{ ...styles.helperText, margin: 0 }}>The same service in several clusters behind one Mimir or Thanos: look at one at a time.</span>
        </div>
      ) : null}

      <div style={panelStyle(hasFindings ? '#b877d9' : '#3fcf8e')}>
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(320px, 0.85fr)', gap: 18, alignItems: 'stretch' }}>
          {/* Packed at the top and kept in view while the symptom list on the right scrolls past. */}
          <div style={{ display: 'grid', gap: 14, alignContent: 'start', alignSelf: 'start', position: 'sticky', top: 16 }}>
            <div style={styles.row}>
              <span style={{ display: 'grid', placeItems: 'center', width: 40, height: 40, borderRadius: 999, border: `1px solid ${hasFindings ? '#b877d9' : '#3fcf8e'}`, color: hasFindings ? '#b877d9' : '#3fcf8e', fontSize: 22 }}>△</span>
              <div>
                <h3 style={{ margin: 0 }}>{headline}</h3>
                <p style={{ ...styles.muted, margin: '6px 0 0' }}>{summaryText}</p>
                {primaryService?.service === NO_SERVICE ? (
                  <p style={{ ...styles.helperText, margin: '6px 0 0' }}>
                    These metrics have no <code>service</code> label, often the monitoring system's own (Prometheus, exporters). Add one at the
                    scrape target to tie them to what they measure.
                  </p>
                ) : null}
              </div>
            </div>
            <div style={styles.row}>
              <span title="Importance combines analyzer confidence, severity, signal count, and observed change size. Higher values should be reviewed first." style={styles.chip}>Highest importance {topFinding ? topFinding.importance.toFixed(2) : '—'} <InfoTip /></span>
              {primaryService ? (
                <span title={`${symptomCount} symptom${symptomCount === 1 ? '' : 's'} on ${serviceLabel(primaryService.service)} (a symptom seen in several runs counts once): ${attentionCount} need attention, ${triage.data.length} data problem${triage.data.length === 1 ? '' : 's'}, ${triage.background.length} background. ${data.summary.findingsGenerated} findings in this window, counting every run.`} style={styles.chip}>{attentionCount} need{attentionCount === 1 ? 's' : ''} attention on {serviceLabel(primaryService.service)} <InfoTip /></span>
              ) : null}
              <span title="Affected metrics are unique metrics with symptoms on this service." style={styles.chip}>{symptomMetrics.length} metric{symptomMetrics.length === 1 ? '' : 's'} affected <InfoTip /></span>
              <span title="First observed is taken from finding comparison data or creation time." style={styles.chip}>First observed {formatCompactDate(topFinding?.firstObserved)} <InfoTip /></span>
            </div>
            {selectedSymptom ? (
              <div>
                <strong>Looking at</strong>{' '}
                <span style={styles.muted}>{metricIn(selectedSymptom.finding)} · {roleLabel(selectedSymptom).toLowerCase()}</span>
                <p style={{ ...styles.helperText, margin: '4px 0 0' }}>
                  {symptomCount > 1 ? 'Pick another one on the right; the buttons act on the one you are looking at. ' : ''}A case is opened per symptom.
                </p>
              </div>
            ) : (
              <div>
                <strong>Recommended next step</strong>
                <p style={{ ...styles.muted, margin: '6px 0 0' }}>No immediate investigation is recommended from this run. Review skipped or failed jobs if coverage looks too narrow.</p>
              </div>
            )}
            <div style={styles.row}>
              <button
                type="button"
                style={{ ...styles.button, background: hasFindings ? '#b877d9' : 'rgba(204, 204, 220, 0.18)', ...(selectedFinding ? {} : disabledActionStyle) }}
                disabled={!selectedFinding}
                title={selectedFinding ? 'Show this symptom below: evidence, trust and its case.' : 'No current-run finding is available to investigate.'}
                onClick={() => selectedFinding && onOpenInvestigation(selectedFinding, 'investigate')}
              >
                Investigate
              </button>
              {caseButton(selectedFinding, selectedCaseId)}
            </div>
            {caseError ? <p style={{ ...styles.helperText, color: '#ff7381', margin: 0 }}>{caseError}</p> : null}
            {openCaseError ? <p style={{ ...styles.helperText, color: '#ff7381', margin: 0 }}>{openCaseError}</p> : null}
          </div>
          <div style={{ borderLeft: '1px solid rgba(204, 204, 220, 0.12)', paddingLeft: 18, minWidth: 0 }}>
            <SymptomTriagePanel
              service={primaryService?.service ?? ''}
              sourceOf={sourceOf}
              triage={triage}
              selected={selectedSymptom}
              caseByFinding={caseByFinding}
              showAll={showAllSymptoms}
              onToggleAll={() => setShowAllSymptoms((current) => !current)}
              onSelect={(symptom) => onOpenInvestigation(symptom.finding, 'investigate')}
              onOpenScope={(finding) => onOpenInvestigation(finding, 'evidence')}
              renderCase={(symptom) => caseButton(symptom.finding, caseForSymptom(symptom, caseByFinding), true)}
              patternsOf={patternsOf}
              onShowBehavior={showBehavior}
            />
          </div>
        </div>
      </div>

      {investigationFinding ? (
        <AutonomousInvestigationPanel
          backendUrl={backendUrl}
          finding={investigationFinding}
          mode={investigationMode}
          position={panelSymptom ? `${roleLabel(panelSymptom)} · ${metricIn(panelSymptom.finding)} on ${serviceLabel(primaryService?.service ?? '')}` : null}
          connection={connectionName(connections, investigationFinding.connection_id)}
          caseAction={caseButton(investigationFinding, panelCaseId)}
          caseId={panelCaseId}
          onOpenInteractive={() => onInvestigateInteractive(investigationFinding)}
          onClose={onCloseInvestigation}
        />
      ) : null}

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 12 }}>
        <GrafanaAutonomousAskPanel askState={askState} />
        <GrafanaFindingsLookupPanel lookupState={findingsLookupState} />
      </div>

      <CurrentRunSummaryPanel data={data} />

      {(servicePriorities.length > 1 || data.behaviorDistribution.length > 1) ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.35fr) minmax(320px, 0.65fr)', gap: 12, alignItems: 'start' }}>
          {servicePriorities.length > 1 ? (
            <ServicePrioritiesPanel
              servicePriorities={servicePriorities}
              findings={findings}
              onInvestigate={(finding) => onOpenInvestigation(finding, 'investigate')}
            />
          ) : null}
          {data.behaviorDistribution.length > 1 ? (
            <ObservedChangesPanel data={data} />
          ) : null}
        </div>
      ) : null}

      <BehaviorFindingsPanel behaviorFindings={behaviorFindings} backendUrl={backendUrl} onCasesChanged={onRetry} include={linkedBehaviorIds} shown={behaviorsShown} onShownChange={setBehaviorsShown} />

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(260px, 0.95fr) minmax(280px, 1fr) minmax(260px, 0.85fr)', gap: 12, alignItems: 'start' }}>
        <CoverageDetailsPanel selection={data.selection} onEnableCategory={onEnableCategory} onPreviewNow={onPreviewNow} isPreviewingNow={isPreviewingNow} previewNowError={previewNowError} />
        <RunHistoryPanel rows={data.executionRows} />
        <CasesPanel data={data} backendUrl={backendUrl} onCasesChanged={onRetry} />
      </div>

      <InvestigationDrawer
        open={drawerCase !== null}
        caseResult={null}
        caseDetails={drawerCase}
        finding={null}
        source={drawerSource}
        backendUrl={backendUrl}
        onClose={closeDrawer}
        onCaseChange={(updated) => {
          setDrawerCase(updated);
          setDrawerChanged(true);
        }}
        onError={setOpenCaseError}
      />
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
  const [shown, setShown] = useSectionShown('run-summary');
  const count = (value: number | null) => (value === null ? '—' : value.toLocaleString());
  return (
    <div style={panelStyle('#68707f')}>
      <div style={styles.rowBetween}>
        <h3 style={{ ...sectionTitleStyle, color: '#f5f7ff', fontSize: 16, textTransform: 'none', margin: 0 }}>Current Run Summary</h3>
        <div style={{ ...styles.row, gap: 10 }}>
          {shown ? null : (
            <span style={{ ...styles.helperText, margin: 0 }}>
              {count(data.summary.executed)} executed · {count(data.summary.skipped)} skipped · {count(data.summary.findingsGenerated)} findings · {count(data.summary.casesOpen)} cases
            </span>
          )}
          <PanelToggle isOpen={shown} tone="#68707f" label="current run summary" onClick={() => setShown(!shown)} />
        </div>
      </div>
      {shown ? (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 10, marginTop: 12 }}>
        {summaryItems.map((item) => (
          <div key={item.label} style={{ border: '1px solid rgba(204, 204, 220, 0.16)', borderRadius: 8, padding: 14, background: 'rgba(17, 18, 23, 0.55)' }}>
            <div style={{ color: item.tone, fontSize: 24, fontWeight: 900 }}>{item.value === null ? '—' : item.value.toLocaleString()}</div>
            <div style={{ fontWeight: 850, marginTop: 5 }}>{item.label}</div>
            <div style={styles.helperText}>{item.detail}</div>
          </div>
        ))}
      </div>
      ) : null}
    </div>
  );
}

function ServicePrioritiesPanel({
  servicePriorities,
  findings,
  onInvestigate,
}: {
  servicePriorities: ReturnType<typeof buildServicePriorities>;
  findings: Finding[];
  /** Shows the service's top finding under the overview's top card. */
  onInvestigate: (finding: Finding) => void;
}) {
  const [shown, setShown] = useSectionShown('service-priorities');
  return (
    <div id="top-findings" style={panelStyle('#ffb357')}>
      <div style={styles.rowBetween}>
        <h3 style={sectionTitleStyle}>Service Priorities <InfoTip title="Services are ranked by their highest-importance current-run symptom. Multiple symptoms on one service are grouped to avoid creating duplicate incident candidates." /></h3>
        <div style={{ ...styles.row, gap: 10 }}>
          <span style={{ ...styles.helperText, margin: 0 }}>
            {servicePriorities.length} service{servicePriorities.length === 1 ? '' : 's'}{shown ? ' shown' : servicePriorities[0] ? ` · top: ${serviceLabel(servicePriorities[0].service)}` : ''}
          </span>
          <PanelToggle isOpen={shown} tone="#ffb357" label="service priorities" onClick={() => setShown(!shown)} />
        </div>
      </div>
      {shown ? (
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.25fr 1fr 1fr 1fr', gap: '10px 14px', fontSize: 12, overflowX: 'auto', alignItems: 'center' }}>
        {['Service', 'Symptoms', 'Metrics affected', 'Highest importance', 'Recommended action'].map((header) => <div key={header} style={styles.tableHeader}>{header}</div>)}
        {servicePriorities.slice(0, 5).map((service, index) => (
          <React.Fragment key={service.service}>
            <div style={{ borderLeft: `4px solid ${index === 0 ? '#b877d9' : index === 1 ? '#5794f2' : '#3fcf8e'}`, paddingLeft: 10 }}>
              <strong>{serviceLabel(service.service)}</strong>
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
                if (finding) onInvestigate(finding);
              }}
            >
              {service.service === NO_SERVICE ? 'Investigate these metrics' : `Investigate ${service.service}`}
            </button>
          </React.Fragment>
        ))}
      </div>
      ) : null}
    </div>
  );
}

function ObservedChangesPanel({ data }: { data: AutonomousDashboardData }) {
  const [shown, setShown] = useSectionShown('observed-changes');
  const total = data.summary.findingsGenerated;
  const top = [...data.behaviorDistribution].sort((a, b) => b.count - a.count)[0];
  return (
    <div style={panelStyle('#ffb357')}>
      <div style={styles.rowBetween}>
        <h3 style={sectionTitleStyle}>Observed Changes <InfoTip title="Observed changes are analyzer-detected metric patterns, such as spikes or baseline shifts. They are not root cause." /></h3>
        <PanelToggle isOpen={shown} tone="#ffb357" label="observed changes" onClick={() => setShown(!shown)} />
      </div>
      {shown ? (
        <BehaviorDonut items={data.behaviorDistribution} total={total} />
      ) : (
        <span style={{ ...styles.helperText, margin: 0 }}>
          {total.toLocaleString()} change{total === 1 ? '' : 's'}{top && total ? ` · mostly ${top.label} (${Math.round((top.count / total) * 100)}%)` : ''}
        </span>
      )}
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
        <PanelToggle isOpen={isOpen} tone="#3fcf8e" label="coverage details" onClick={() => setIsOpen((current) => !current)} />
      </div>
      {isOpen ? <div style={{ marginTop: 14 }}><MetricSelectionFunnel selection={selection} onEnableCategory={onEnableCategory} onPreviewNow={onPreviewNow} isPreviewingNow={isPreviewingNow} previewNowError={previewNowError} /></div> : null}
    </div>
  );
}

function RunHistoryPanel({ rows }: { rows: AutonomousDashboardData['executionRows'] }) {
  const [isOpen, setIsOpen] = useState(false);
  const recent = rows.slice(0, 5);
  const failed = recent.filter((row) => row.status.toLowerCase() === 'failed').length;
  return (
    <div style={panelStyle('#5794f2')}>
      <div style={styles.rowBetween}>
        <div>
          <h3 style={{ ...sectionTitleStyle, color: '#f5f7ff', fontSize: 16, textTransform: 'none' }}>Run History <InfoTip title="Recent autonomous runs. Failures here may indicate overly broad scope or queries returning multiple series." /></h3>
          <div style={{ ...styles.row, color: '#cfd3e6' }}>
            {recent.length ? (
              <>
                <span>{recent.length} recent {recent.length === 1 ? 'run' : 'runs'}</span>
                {failed ? <><span>·</span><span style={{ color: '#ff7381' }}>{failed} failed</span></> : null}
                <span>·</span>
                <span>latest {formatCompactDate(recent[0].completed)}</span>
              </>
            ) : <span>No runs yet</span>}
          </div>
        </div>
        {recent.length ? <PanelToggle isOpen={isOpen} tone="#5794f2" label="run history" onClick={() => setIsOpen((current) => !current)} /> : null}
      </div>
      {!isOpen ? null : rows.length ? (
        <div style={{ display: 'grid', gap: 8, marginTop: 14 }}>
          {recent.map((row) => (
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

/** Show/Hide for the overview's summary panels, which start collapsed to leave room below. */
function PanelToggle({ isOpen, tone, label, onClick }: { isOpen: boolean; tone: string; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-expanded={isOpen}
      aria-label={`${isOpen ? 'Hide' : 'Show'} ${label}`}
      onClick={onClick}
      style={{ ...styles.chip, background: 'transparent', color: '#f5f7ff', borderColor: `${tone}88`, cursor: 'pointer', whiteSpace: 'nowrap' }}
    >
      {isOpen ? 'Hide ▴' : 'Show ▾'}
    </button>
  );
}

/** Recent cases; clicking one opens it in the case workflow drawer (the same one Interactive
 * Analysis uses), so it can be investigated, resolved and published to memory without leaving
 * Grafana. The overview is refreshed on close when anything was saved, so statuses stay current. */
export function CasesPanel({ data, backendUrl, onCasesChanged }: { data: AutonomousDashboardData; backendUrl: string; onCasesChanged?: () => void }) {
  const [isOpen, setIsOpen] = useState(false);
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

  const recent = data.recentCases.slice(0, 5);
  const openCount = recent.filter((caseItem) => !/^(resolved|closed)\b/i.test(caseItem.status)).length;
  return (
    <div style={panelStyle('#b877d9')}>
      <div style={styles.rowBetween}>
        <div>
          <h3 style={{ ...sectionTitleStyle, color: '#f5f7ff', fontSize: 16, textTransform: 'none' }}>{data.casesScope === 'current_run' ? 'Cases Created From This Run' : 'Recent Cases from History'} <InfoTip title="Cases are investigation records. Current-run cases are linked to findings generated by this run." /></h3>
          <div style={{ ...styles.row, color: '#cfd3e6' }}>
            {recent.length ? (
              <>
                <span>{recent.length} {recent.length === 1 ? 'case' : 'cases'}</span>
                <span>·</span>
                <span style={{ color: openCount ? '#ffb357' : undefined }}>{openCount} open</span>
              </>
            ) : <span>No cases yet</span>}
          </div>
        </div>
        {recent.length ? <PanelToggle isOpen={isOpen} tone="#b877d9" label="cases" onClick={() => setIsOpen((current) => !current)} /> : null}
      </div>
      {!isOpen ? null : data.recentCases.length ? (
        <div style={{ ...styles.stack, marginTop: 14 }}>
          {recent.map((caseItem) => (
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

/** Recent behavior findings with Create Case / Open Case; the case opens in the investigation drawer. */
export function BehaviorFindingsPanel({ behaviorFindings, backendUrl, onCasesChanged, include = [], shown = true, onShownChange }: {
  behaviorFindings: BehaviorFinding[];
  backendUrl: string;
  onCasesChanged?: () => void;
  /** Hidden by the viewer: a one-line count stays, with Show. Without onShownChange it can't be hidden. */
  shown?: boolean;
  onShownChange?: (shown: boolean) => void;
  /** Shown even when older than the five most recent: the matches a symptom's "Part of" chip points at. */
  include?: number[];
}) {
  const [openCase, setOpenCase] = useState<GrafanaCase | null>(null);
  const [openError, setOpenError] = useState('');
  const [caseChanged, setCaseChanged] = useState(false);
  const recent = useMemo(() => {
    const newest = [...behaviorFindings].sort((a, b) => (b.last_seen_at ?? '').localeCompare(a.last_seen_at ?? ''));
    const shown = newest.slice(0, 5);
    return [...shown, ...newest.slice(5).filter((behavior) => include.includes(behavior.id))];
  }, [behaviorFindings, include]);

  if (!recent.length) return null;

  async function openCaseById(caseId: number) {
    setOpenError('');
    try {
      setOpenCase(await getCase(backendUrl, caseId));
      // A new case changes the Cases panel, so refresh the overview when the drawer closes.
      setCaseChanged(true);
    } catch {
      setOpenError(`Could not open case #${caseId}. Check the backend connection and retry.`);
    }
  }

  function closeCase() {
    setOpenCase(null);
    if (caseChanged) onCasesChanged?.();
    setCaseChanged(false);
  }

  return (
    <div style={panelStyle('#5794f2')}>
      {shown ? (
        <PluginBehaviorFindings
          backendUrl={backendUrl}
          findings={recent}
          onOpenCase={openCaseById}
          frame={{ border: 0, padding: 0 }}
          headerAction={onShownChange ? <PanelToggle isOpen tone="#5794f2" label="behavior findings" onClick={() => onShownChange(false)} /> : null}
        />
      ) : (
        <div style={styles.rowBetween}>
          <span>
            <strong>Behavior findings</strong>{' '}
            <span style={{ ...styles.helperText, margin: 0 }}>
              {behaviorFindings.length} match{behaviorFindings.length === 1 ? '' : 'es'} · {behaviorFindings.filter((item) => !item.case_id).length} without a case
            </span>
          </span>
          <PanelToggle isOpen={false} tone="#5794f2" label="behavior findings" onClick={() => onShownChange?.(true)} />
        </div>
      )}
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
              <strong>{finding.service} / {finding.metric_name}{finding.cluster ? ` · ${finding.cluster}` : ''}</strong>
              <div style={styles.helperText}>{finding.plain ? `${finding.plain.badge_label}: ${finding.plain.headline}` : finding.title}</div>
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

const METRIC_ROWS_SHOWN = 5;
const DATA_CHIPS_SHOWN = 8;
const metricIn = (finding: Finding) => (finding.cluster ? `${finding.metric_name} in ${finding.cluster}` : finding.metric_name);

/** The cluster (and connection) a finding came from; nothing for single-cluster data. */
function SourceChip({ source }: { source: string | null }) {
  if (!source) return null;
  return <span title="Cluster and Prometheus connection the data came from" style={{ ...styles.chip, color: '#8ab8ff', borderColor: 'rgba(87, 148, 242, 0.45)' }}>{source}</span>;
}

function formatSince(value?: string | null) {
  return value ? new Date(value).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '';
}

function formatClock(value?: string | null) {
  return value ? new Date(value).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }) : '';
}

function formatDuration(from?: string | null, to?: string | null) {
  if (!from || !to) return '';
  const minutes = Math.max(1, Math.round((Date.parse(to) - Date.parse(from)) / 60_000));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} h` : `${Math.round(hours / 24)} days`;
}

/** "Ongoing for 11 h, since Oct 8, 5:30 PM" while it still shows in the latest runs, else when it was seen. */
function symptomTiming(symptom: ServiceSymptom, latestSeen: string | null) {
  const runs = `${symptom.runs.length} run${symptom.runs.length === 1 ? '' : 's'}`;
  if (stillShowing(symptom, latestSeen)) {
    return `Ongoing for ${formatDuration(symptom.firstSeen, latestSeen)}, since ${formatSince(symptom.firstSeen)} · ${runs}`;
  }
  return `Seen ${formatSince(symptom.firstSeen)} to ${formatClock(symptom.lastSeen)} · ${runs}`;
}

/** A service's symptoms sorted into what to act on (one row per metric, with what changed, for how
 * long, and its case), data problems to fix first, and folded background signals. Clicking a row
 * shows it in the finding panel below. */
function SymptomTriagePanel({ service, sourceOf: sourceOfAll, triage, selected, caseByFinding, showAll, onToggleAll, onSelect, onOpenScope, renderCase, patternsOf = () => [], onShowBehavior }: {
  service: string;
  /** "us · Team A": the cluster and connection, when there are several. */
  sourceOf: (finding: Finding) => string | null;
  triage: SymptomTriage;
  selected: ServiceSymptom | null;
  caseByFinding: Map<number, number>;
  showAll: boolean;
  onToggleAll: () => void;
  onSelect: (symptom: ServiceSymptom) => void;
  /** The pod-scope chip ("where") opens the finding's evidence. */
  onOpenScope: (finding: Finding) => void;
  /** The behavior matches (several metrics together) a symptom is part of. */
  patternsOf?: (symptom: ServiceSymptom) => BehaviorFinding[];
  /** Brings that match into view in the Behavior findings panel, opening it when hidden. */
  onShowBehavior?: (id: number) => void;
  renderCase: (symptom: ServiceSymptom) => React.ReactNode;
}) {
  const [showBackground, setShowBackground] = useState(false);
  const [showAllData, setShowAllData] = useState(false);
  // Every symptom from one cluster/connection: say it once in the heading, not on each one.
  const allSymptoms = [...triage.attention.flatMap((row) => [row.lead, ...row.others]), ...triage.data, ...triage.background];
  const sources = new Set(allSymptoms.map((symptom) => sourceOfAll(symptom.finding)));
  const sharedSource = sources.size === 1 ? [...sources][0] : null;
  const sourceOf = (finding: Finding) => (sharedSource ? null : sourceOfAll(finding));
  const dataByMetric = dataProblemsByMetric(triage.data, (symptom) => `${symptom.finding.metric_name}|${sourceOfAll(symptom.finding) ?? ''}|${symptom.finding.cluster ?? ''}`);
  const dataShown = showAllData ? dataByMetric : dataByMetric.slice(0, DATA_CHIPS_SHOWN);
  const rows = showAll ? triage.attention : triage.attention.slice(0, METRIC_ROWS_SHOWN);
  const withCase = triage.attention.filter((row) => caseForSymptom(row.lead, caseByFinding) !== null).length;
  const firstSeen = triage.attention.map((row) => row.lead.firstSeen).filter((value): value is string => Boolean(value)).sort()[0];
  const nothing = !triage.attention.length && !triage.data.length && !triage.background.length;
  const selectable = (symptom: ServiceSymptom, children: React.ReactNode, style: React.CSSProperties, testId: string) => {
    const isSelected = symptom === selected;
    return (
      <div
        key={symptomKey(symptom)}
        data-testid={testId}
        role="button"
        tabIndex={0}
        aria-pressed={isSelected}
        aria-label={`Look at ${symptom.finding.metric_name}${symptom.finding.cluster ? ` in ${symptom.finding.cluster}` : ''} ${symptomKind(symptom.finding)}`}
        onClick={() => onSelect(symptom)}
        onKeyDown={(event) => {
          if (event.target !== event.currentTarget) return;
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            onSelect(symptom);
          }
        }}
        style={{ cursor: 'pointer', ...style, ...(isSelected ? { border: '1px solid rgba(87, 148, 242, 0.6)', background: 'rgba(87, 148, 242, 0.1)' } : {}) }}
      >
        {children}
      </div>
    );
  };
  const groupTitle = (title: string, detail: string) => (
    <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap', margin: '12px 0 6px' }}>
      <strong style={{ fontSize: 13 }}>{title}</strong>
      <span style={{ ...styles.helperText, margin: 0 }}>{detail}</span>
    </div>
  );

  return (
    <div data-testid="symptom-triage">
      <div style={{ ...styles.rowBetween, marginBottom: 4 }}>
        <h3 style={{ ...sectionTitleStyle, margin: 0 }}>{service ? `${serviceLabel(service)}: what's going on` : 'Related Symptoms'} <InfoTip title="This service's findings in the window, sorted by what to do with them. A finding seen in several runs is listed once." /></h3>
        {sharedSource ? <span style={{ ...styles.helperText, margin: 0 }}>All from {sharedSource}</span> : null}
      </div>
      {nothing ? <p style={styles.muted}>No symptoms were detected in this run.</p> : null}
      {triage.attention.length ? (
        <div style={{ fontSize: 13 }}>
          <strong>{triage.attention.length} metric{triage.attention.length === 1 ? '' : 's'} need{triage.attention.length === 1 ? 's' : ''} attention</strong>
          <span style={styles.muted}>{firstSeen ? ` since ${formatSince(firstSeen)}` : ''} · {withCase} of {triage.attention.length} {withCase === 1 ? 'has' : 'have'} a case</span>
        </div>
      ) : null}

      {triage.attention.length ? (
        <>
          {groupTitle('Needs attention', 'strong or moderate evidence')}
          {rows.map((row) => {
            const change = symptomChange(row.lead.finding);
            return selectable(row.lead, (
              <>
                <div style={{ minWidth: 0 }}>
                  <div style={{ ...styles.row, gap: 8 }}>
                    <strong>{row.lead.finding.metric_name}</strong>
                    <SourceChip source={sourceOf(row.lead.finding)} />
                    {row.lead.finding.plain ? (
                      <>
                        <PluginPlainBadge plain={row.lead.finding.plain} />
                        <span>{row.lead.finding.plain.headline}</span>
                      </>
                    ) : (
                      <>
                        {change ? <span>{change.text}</span> : <span style={styles.muted}>{symptomKind(row.lead.finding)}</span>}
                        {change?.percent ? <strong style={{ color: '#ff7381' }}>{change.percent}</strong> : null}
                      </>
                    )}
                  </div>
                  <div style={{ ...styles.row, gap: 6, marginTop: 3 }}>
                    <span style={{ ...styles.helperText, margin: 0 }}>{symptomTiming(row.lead, triage.latestSeen)}</span>
                    <span onClick={(event) => event.stopPropagation()}><SymptomScopeChip finding={row.lead.finding} onOpen={onOpenScope} /></span>
                    {patternsOf(row.lead).map((behavior) => <PartOfChip key={behavior.id} behavior={behavior} onShow={onShowBehavior} />)}
                  </div>
                  {row.others.length ? (
                    <div style={{ ...styles.helperText, marginTop: 2 }}>
                      Also on this metric: {row.others.map((other) => `${symptomKind(other.finding)}${symptomRole(other.finding) === 'background' ? ' (weak)' : ''}`).join(', ')}
                    </div>
                  ) : null}
                </div>
                <div onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>{renderCase(row.lead)}</div>
              </>
            ), { display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto', gap: 12, alignItems: 'center', padding: 10, border: '1px solid rgba(204, 204, 220, 0.12)', borderRadius: 8, marginBottom: 8 }, 'triage-attention');
          })}
          {triage.attention.length > METRIC_ROWS_SHOWN ? (
            <button type="button" style={{ ...styles.tableRowButton, fontWeight: 600 }} onClick={onToggleAll}>
              {showAll ? `Show top ${METRIC_ROWS_SHOWN}` : `Show ${triage.attention.length - METRIC_ROWS_SHOWN} more`}
            </button>
          ) : null}
        </>
      ) : null}

      {triage.data.length ? (
        <>
          {groupTitle('Fix the data first', 'monitoring, not the service')}
          <div data-testid="triage-data" style={{ border: '1px solid rgba(255, 179, 87, 0.4)', background: 'rgba(255, 179, 87, 0.07)', borderRadius: 8, padding: '10px 12px' }}>
            <strong style={{ color: '#ffb357' }}>{dataByMetric.length} metric{dataByMetric.length === 1 ? '' : 's'} stopped reporting or froze</strong>
            <div style={{ fontSize: 12, marginTop: 2 }}>
              {dataByMetric.length > 1
                ? 'When several metrics on one service stop together, the cause is usually collection (the scrape target or exporter), not the service. '
                : ''}
              Until it is fixed, gaps can hide changes or fake them.
            </div>
            <div style={{ ...styles.row, gap: 6, marginTop: 8 }}>
              {dataShown.map(({ latest, episodes }) => selectable(latest, (
                <span>
                  {metricIn(latest.finding)}{sourceOf(latest.finding) ? ` (${sourceOf(latest.finding)})` : ''}
                  <span style={styles.muted}>{episodes > 1 ? ` · ${episodes} episodes, latest` : ''} · {symptomTiming(latest, triage.latestSeen).replace(/^Ongoing for [^,]+, /, '')}</span>
                </span>
              ), { ...styles.chip, fontSize: 12 }, 'triage-data-metric'))}
            </div>
            {dataByMetric.length > DATA_CHIPS_SHOWN ? (
              <button type="button" style={{ ...styles.tableRowButton, fontWeight: 600, marginTop: 6 }} onClick={() => setShowAllData(!showAllData)}>
                {showAllData ? `Show the latest ${DATA_CHIPS_SHOWN}` : `Show ${dataByMetric.length - DATA_CHIPS_SHOWN} more`}
              </button>
            ) : null}
          </div>
        </>
      ) : null}

      {triage.background.length ? (
        <div data-testid="triage-background" style={{ border: '1px dashed rgba(204, 204, 220, 0.22)', borderRadius: 8, padding: '8px 12px', marginTop: 12 }}>
          <div style={styles.rowBetween}>
            <span><strong style={{ fontSize: 13 }}>Background</strong> <span style={{ ...styles.helperText, margin: 0 }}>{triage.background.length} weaker signal{triage.background.length === 1 ? '' : 's'}, real about as often as a random alert in tests</span></span>
            <button type="button" style={{ ...styles.tableRowButton, fontWeight: 600 }} aria-expanded={showBackground} onClick={() => setShowBackground(!showBackground)}>{showBackground ? 'Hide' : 'Show'}</button>
          </div>
          {showBackground ? (
            <div style={{ ...styles.stack, gap: 4, marginTop: 6 }}>
              {triage.background.map((symptom) => selectable(symptom, (
                <span style={{ fontSize: 13 }}>{symptom.finding.metric_name}{sourceOf(symptom.finding) ? ` (${sourceOf(symptom.finding)})` : ''}: {symptomKind(symptom.finding)} <span style={styles.muted}>· {symptomTiming(symptom, triage.latestSeen)}</span></span>
              ), { border: '1px solid transparent', borderRadius: 6, padding: '4px 6px' }, 'triage-background-item'))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/** "Part of: <match> · N metrics": scrolls to that match in the Behavior findings panel. */
function PartOfChip({ behavior, onShow }: { behavior: BehaviorFinding; onShow?: (id: number) => void }) {
  const metrics = patternParts(behavior).length;
  return (
    <button
      type="button"
      data-testid="symptom-part-of"
      title="This symptom is one of the metrics a behavior pattern matched together: one problem, not several."
      onClick={(event) => {
        event.stopPropagation();
        if (onShow) onShow(behavior.id);
        else document.getElementById(behaviorAnchor(behavior.id))?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
      }}
      onKeyDown={(event) => event.stopPropagation()}
      style={{ ...styles.chip, padding: '2px 9px', fontSize: 11, fontWeight: 600, cursor: 'pointer', color: '#9ab8ff', borderColor: 'rgba(110, 159, 255, 0.55)', background: 'rgba(110, 159, 255, 0.08)' }}
    >
      Part of: {behavior.title}{metrics > 1 ? ` · ${metrics} metrics` : ''}
    </button>
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

/** The finding being looked at, right under the overview's top card: evidence, trust, and its case
 * (`caseAction` is Create case / Open case #N; the case itself opens in the drawer). */
function AutonomousInvestigationPanel({
  backendUrl,
  finding,
  mode,
  position,
  connection = null,
  caseAction,
  caseId,
  onOpenInteractive,
  onClose,
}: {
  backendUrl: string;
  finding: Finding;
  mode: 'investigate' | 'evidence';
  /** What it is on the service ("Needs attention · error_rate on trend-lab"), when it is one of its symptoms. */
  position: string | null;
  /** The connection's name, when there are several connections. */
  connection?: string | null;
  caseAction: React.ReactNode;
  caseId: number | null;
  onOpenInteractive: () => void;
  onClose: () => void;
}) {
  const { canEdit } = usePermissions();
  const breakdown = findingBreakdown(finding);
  // The breakdown has its own section; the raw comparison view shows the rest.
  const { breakdown: _breakdown, ...comparison } = finding.comparison_json ?? {};
  const comparisonEntries = Object.entries(comparison).filter(([, value]) => value !== null && value !== undefined);
  const activeCaseId = caseId;
  const [ticket, setTicket] = useState<CaseTicketLink | null>(null);
  const [isTicketLoading, setIsTicketLoading] = useState(false);
  const [ticketOperation, setTicketOperation] = useState<CaseTicketOperation | null>(null);
  const [ticketError, setTicketError] = useState('');
  const [ticketingStatus, setTicketingStatus] = useState<{ enabled: boolean } | null>(null);
  const [ticketingStatusFailed, setTicketingStatusFailed] = useState(false);

  useEffect(() => {
    if (!backendUrl) return;
    let isMounted = true;
    getTicketingStatus(backendUrl)
      .then((status) => {
        if (isMounted) setTicketingStatus(status);
      })
      .catch(() => {
        if (isMounted) setTicketingStatusFailed(true);
      });
    return () => {
      isMounted = false;
    };
  }, [backendUrl]);

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
      <div style={{ ...styles.rowBetween, alignItems: 'flex-start' }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={styles.helperText}>
            {position ?? `${mode === 'evidence' ? 'Evidence' : 'Investigation'} / Current Finding`}
          </div>
          {finding.plain ? <div style={{ marginTop: 6 }}><PluginPlainBadge plain={finding.plain} /></div> : null}
          <h3 style={{ margin: '4px 0 0' }}>{finding.plain?.headline ?? finding.title}</h3>
          {finding.plain ? (
            <div style={{ marginTop: 6 }}><PluginPlainFinding plain={finding.plain} details={`${finding.title} ${finding.summary}`} /></div>
          ) : (
            <p style={{ ...styles.muted, margin: '6px 0 0' }}>{finding.summary}</p>
          )}
        </div>
        <div style={{ ...styles.row, flex: 'none' }}>
          {caseAction}
          <button type="button" style={{ ...styles.button, background: 'rgba(204, 204, 220, 0.08)' }} title="Open this service and metric in Interactive Analysis, with the full metric timeline." onClick={onOpenInteractive}>Open in Interactive Analysis</button>
          <button type="button" style={{ ...styles.button, background: 'rgba(204, 204, 220, 0.08)' }} onClick={onClose}>Close</button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(240px, 0.75fr) minmax(280px, 1fr)', gap: 12, marginTop: 14 }}>
        <div style={{ ...styles.stack, border: '1px solid rgba(204, 204, 220, 0.12)', borderRadius: 8, padding: 14 }}>
          <div style={styles.row}>
            <SeverityPill severity={finding.health_status} />
            <BehaviorPill label={humanize(finding.category)} />
            {caseId !== null ? <span style={{ ...styles.chip, color: '#3fcf8e', borderColor: 'rgba(63, 207, 142, 0.5)' }}>Case #{caseId}</span> : null}
            <PluginCustomSettingsChip finding={finding} />
          </div>
          <div style={styles.detailGrid}>
            <div><div style={styles.helperText}>Service</div><strong>{finding.service || 'unknown'}</strong></div>
            <div><div style={styles.helperText}>Metric</div><strong>{finding.metric_name}</strong></div>
            <div><div style={styles.helperText}>Importance</div><strong>{finding.importance_score.toFixed(2)}</strong></div>
            <div><div style={styles.helperText}>Analysis run</div><strong>{finding.analysis_run_id || 'unknown'}</strong></div>
            {finding.cluster ? <div><div style={styles.helperText}>Cluster</div><strong>{finding.cluster}</strong></div> : null}
            {connection ? <div><div style={styles.helperText}>Prometheus connection</div><strong>{connection}</strong></div> : null}
          </div>
          <PluginCustomSettings finding={finding} />
          <PluginFindingTrust backendUrl={backendUrl} findingId={finding.id} trust={finding.trust} service={finding.service} />
          {activeCaseId && shouldShowTicketCard(ticketingStatus, ticketingStatusFailed, ticket) ? (
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
                    disabled={isTicketLoading || !canEdit}
                    onClick={handleCreateTicket}
                    title={canEdit ? 'Create Jira issue for this case' : LOCK_REASONS.createCase}
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

  // Metrics with no service label (often the monitoring system's own) go after every named service.
  return Object.values(grouped).sort((a, b) => Number(a.service === NO_SERVICE) - Number(b.service === NO_SERVICE) || b.highestImportance - a.highestImportance);
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
        {result.excluded_jobs ? <Kpi label="Excluded before planning" value={result.excluded_jobs} /> : null}
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
  connectionLabel = null,
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
  /** The connection the plan is for, when there are several. */
  connectionLabel?: string | null;
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
  const { canEdit } = usePermissions();
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
          <h2 style={{ margin: 0 }}>Metric Plan Preview{connectionLabel ? `: ${connectionLabel}` : ''}</h2>
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
          {isRunningOnce ? 'Running autonomous analysis...' : `${canEdit ? '' : '🔒 '}Run autonomous analysis once`}
        </button>
        {canEdit ? null : <LockReason style={{ marginTop: 0 }}>{LOCK_REASONS.saveOrRun}</LockReason>}
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
