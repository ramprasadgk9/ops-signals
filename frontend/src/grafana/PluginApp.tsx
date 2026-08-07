import React from 'react';
import { useEffect, useMemo, useState } from 'react';
import { listAnalysisRuns, listAutonomousScopeOptions, listCases, listFindings, previewAutonomousPlan, runAutonomousPlanOnce, runPrometheusSampleAnalysis } from './backendClient';
import { buildTimeRange, calculateIntervalMs, createRelativeTimeRange, formatDateTimeLocal, parseDateTimeLocal, readGrafanaTimeRange } from './grafanaTimeRange';
import {
  discoverMetricNames,
  discoverLabelValues,
  discoverServiceValues,
  listPrometheusDatasources,
  queryPrometheusDatasource,
  type PrometheusDatasourceRef,
} from './grafanaPrometheus';
import { PanelPreview } from './PanelPreview';
import { Card, Field, styles } from './plainUi';
import { buildMetricQuery, type MetricMode } from './prometheusQueryBuilder';
import { normalizePrometheusFrames } from './prometheusFrameNormalizer';
import type { AutonomousPlanItem, AutonomousPreviewResponse, AutonomousRunResponse, GrafanaAnalysisResult, GrafanaCase, GrafanaQueryTarget, MonitoringCategory } from './contracts';
import type { AnalysisRun, Finding } from '../types';
import { buildAutonomousPreviewRequest, filterPreviewRows, previewRowExplanation } from './autonomousPreviewModel';

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
  const [overviewCases, setOverviewCases] = useState<GrafanaCase[]>([]);
  const [overviewError, setOverviewError] = useState('');
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
  const [executionInterval, setExecutionInterval] = useState('10m');
  const [analysisWindow, setAnalysisWindow] = useState('24h');
  const [maxMetricsPerRun, setMaxMetricsPerRun] = useState(500);
  const [maxParallelJobs, setMaxParallelJobs] = useState(20);
  const [previewResult, setPreviewResult] = useState<AutonomousPreviewResponse | null>(null);
  const [previewError, setPreviewError] = useState('');
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [autonomousRunResult, setAutonomousRunResult] = useState<AutonomousRunResponse | null>(null);
  const [autonomousRunError, setAutonomousRunError] = useState('');
  const [isAutonomousRunning, setIsAutonomousRunning] = useState(false);

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
    try {
      const [runs, findings, cases] = await Promise.all([
      listAnalysisRuns(backendUrl),
      listFindings(backendUrl, { window: '24h' }),
      listCases(backendUrl, { limit: 10 }),
      ]);
      if (!active) return;
      setOverviewRuns(runs);
      setOverviewFindings(findings);
      setOverviewCases(cases);
    } catch (overviewLoadError) {
      if (!active) return;
      const message = overviewLoadError instanceof Error ? overviewLoadError.message : 'Autonomous overview unavailable.';
      setOverviewError(message);
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
    listAutonomousScopeOptions(backendUrl, { serviceLabel, namespaceLabel, environmentLabel })
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
  }, [activeMode, backendUrl, serviceLabel, namespaceLabel, environmentLabel]);

  const selectedDatasource = useMemo(
    () => prometheusDatasources.find((datasource) => datasource.uid === selectedPrometheusUid),
    [prometheusDatasources, selectedPrometheusUid]
  );
  const backendReady = useMemo(() => Boolean(backendUrl), [backendUrl]);
  const ready = Boolean(selectedPrometheusUid && target.service && target.metric);
  const timeRangeValid = timeRange.from.getTime() < timeRange.to.getTime();

  function setRange(nextFrom: Date, nextTo: Date) {
    setTimeRange(buildTimeRange(nextFrom, nextTo));
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
          cases={overviewCases}
          isLoading={isLoadingOverview}
          error={overviewError}
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
          runResult={autonomousRunResult}
          runError={autonomousRunError}
          isRunningOnce={isAutonomousRunning}
          onPreview={async () => {
            if (!selectedCategories.length) {
              setPreviewError('Select at least one monitoring category.');
              return;
            }
            setIsPreviewing(true);
            setPreviewError('');
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
            } catch (previewLoadError) {
              const message = previewLoadError instanceof Error ? previewLoadError.message : 'Preview failed.';
              setPreviewError(message);
            } finally {
              setIsPreviewing(false);
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
            } catch (runLoadError) {
              const message = runLoadError instanceof Error ? runLoadError.message : 'Autonomous analysis failed.';
              setAutonomousRunError(message);
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
        subtitle="Continuously monitor many metrics"
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
  cases,
  isLoading,
  error,
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
  runResult,
  runError,
  isRunningOnce,
  onPreview,
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
  cases: GrafanaCase[];
  isLoading: boolean;
  error: string;
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
  maxMetricsPerRun: number;
  setMaxMetricsPerRun: (value: number) => void;
  maxParallelJobs: number;
  setMaxParallelJobs: (value: number) => void;
  previewResult: AutonomousPreviewResponse | null;
  previewError: string;
  isPreviewing: boolean;
  runResult: AutonomousRunResponse | null;
  runError: string;
  isRunningOnce: boolean;
  onPreview: () => Promise<void>;
  onRunOnce: () => Promise<void>;
}) {
  const discoveredMetricCount = new Set(runs.map((run) => `${run.service}:${run.metric_name}`)).size;
  const analyzedCount = runs.length;
  const skippedCount = Math.max(discoveredMetricCount - analyzedCount, 0);
  const openCaseCount = cases.filter((caseItem) => !['resolved', 'closed', 'completed'].includes(caseItem.case_status.toLowerCase())).length;
  const recentRuns = runs.slice(0, 5);
  const recentFindings = findings.slice(0, 5);
  const recentCases = cases.slice(0, 5);
  const [previewStatusFilter, setPreviewStatusFilter] = useState<'all' | 'planned' | 'excluded'>('all');
  const [previewCategoryFilter, setPreviewCategoryFilter] = useState<string>('all');
  const [previewConceptFilter, setPreviewConceptFilter] = useState<string>('all');
  const [expandedPreviewMetric, setExpandedPreviewMetric] = useState<string | null>(null);
  const findingTypes = findings.reduce<Record<string, number>>((acc, finding) => {
    const key = finding.category || finding.health_status || 'unknown';
    acc[key] = (acc[key] ?? 0) + 1;
    return acc;
  }, {});
  const previewRows = filterPreviewRows(previewResult?.items ?? [], previewStatusFilter, previewCategoryFilter, previewConceptFilter);
  const canPreview = Boolean(selectedPrometheusUid && backendUrl && selectedCategories.length);
  const canRunOnce = Boolean(previewResult?.planned_jobs && !isRunningOnce);
  const toggleCategory = (category: MonitoringCategory) => {
    if (selectedCategories.includes(category)) {
      setSelectedCategories(selectedCategories.filter((item) => item !== category));
    } else {
      setSelectedCategories([...selectedCategories, category]);
    }
  };
  const readMultiSelect = (event: React.ChangeEvent<HTMLSelectElement>) => Array.from(event.target.selectedOptions).map((option) => option.value);

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <Card>
        <div style={{ ...styles.rowBetween, alignItems: 'flex-start', marginBottom: 14 }}>
          <div>
            <h2 style={{ margin: 0, color: '#3fcf8e' }}>Autonomous Analysis</h2>
            <p style={{ ...styles.muted, margin: '5px 0 0' }}>Define what to monitor and run the planned metrics once. Continuous scheduling is still intentionally separate.</p>
          </div>
          <span style={{ ...styles.chip, color: '#3fcf8e' }}>Run once enabled</span>
        </div>
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
          <Field label="Policy">
            <select style={styles.input} defaultValue="production-critical">
              <option value="production-critical">Production Critical Services</option>
              <option value="all-observed">All Observed Metrics</option>
              <option value="service-focused">Service Focused Watch</option>
            </select>
          </Field>
          <button type="button" style={{ ...styles.button, ...styles.buttonDisabled }} disabled>
            Manage policies soon
          </button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 0.35fr) minmax(320px, 1fr) minmax(220px, 0.35fr)', gap: 14, marginTop: 16 }}>
          <div style={panelStyle('#73bf69')}>
            <h3 style={sectionTitleStyle}>Analysis scope</h3>
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
            <h3 style={sectionTitleStyle}>What do you want to monitor?</h3>
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
            <h3 style={sectionTitleStyle}>Execution</h3>
            <Field label="Every">
              <select style={styles.input} value={executionInterval} onChange={(event) => setExecutionInterval(event.target.value)}>
                <option value="5m">5 minutes</option>
                <option value="10m">10 minutes</option>
                <option value="30m">30 minutes</option>
                <option value="1h">1 hour</option>
              </select>
            </Field>
            <Field label="Analysis window">
              <select style={styles.input} value={analysisWindow} onChange={(event) => setAnalysisWindow(event.target.value)}>
                <option value="6h">6h</option>
                <option value="24h">24h</option>
                <option value="7d">7d</option>
              </select>
            </Field>
            <Field label="Max metrics per run">
              <input style={styles.input} type="number" value={maxMetricsPerRun} min={1} max={5000} onChange={(event) => setMaxMetricsPerRun(Number(event.target.value))} />
            </Field>
            <Field label="Max parallel jobs">
              <input style={styles.input} type="number" value={maxParallelJobs} min={1} max={200} onChange={(event) => setMaxParallelJobs(Number(event.target.value))} />
            </Field>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 1fr) minmax(220px, 1fr)', gap: 12, marginTop: 16 }}>
          <button type="button" style={canPreview && !isPreviewing ? styles.button : { ...styles.button, ...styles.buttonDisabled }} disabled={!canPreview || isPreviewing} onClick={onPreview}>
            {isPreviewing ? 'Building preview...' : 'Preview metric plan'}
          </button>
          <button type="button" style={canRunOnce ? { ...styles.button, background: 'linear-gradient(135deg, #3fcf8e, #197a4d)' } : { ...styles.button, ...styles.buttonDisabled, background: 'rgba(63, 207, 142, 0.2)' }} disabled={!canRunOnce} onClick={onRunOnce}>
            {isRunningOnce ? 'Running planned jobs...' : 'Run autonomous analysis once'}
          </button>
        </div>
        <div style={styles.helperText}>Preview first, then run the planned jobs once. Repeating scheduler execution can be enabled after this path is validated.</div>
        {previewError && <div style={{ ...styles.alert, marginTop: 12 }}>{previewError}</div>}
        {runError && <div style={{ ...styles.alert, marginTop: 12 }}>{runError}</div>}
      </Card>

      <AutonomousRunPanel result={runResult} />

      <PreviewPlanPanel
        result={previewResult}
        rows={previewRows}
        statusFilter={previewStatusFilter}
        setStatusFilter={setPreviewStatusFilter}
        categoryFilter={previewCategoryFilter}
        setCategoryFilter={setPreviewCategoryFilter}
        conceptFilter={previewConceptFilter}
        setConceptFilter={setPreviewConceptFilter}
        expandedMetric={expandedPreviewMetric}
        setExpandedMetric={setExpandedPreviewMetric}
      />

      <Card>
        <div style={styles.rowBetween}>
          <div>
            <h2 style={{ margin: 0 }}>Autonomous Monitoring Overview</h2>
            <p style={{ ...styles.muted, margin: '5px 0 0' }}>Backfilled from existing analysis runs, findings, and cases APIs.</p>
          </div>
          <span style={{ ...styles.chip, color: isLoading ? '#ffb357' : '#3fcf8e' }}>{isLoading ? 'Loading overview' : 'Existing APIs'}</span>
        </div>
        {error && <div style={{ ...styles.alert, marginTop: 12 }}>{error}</div>}
        <div style={{ ...styles.compactStats, marginTop: 16 }}>
          <Kpi label="Metrics discovered" value={discoveredMetricCount} />
          <Kpi label="Analyzed" value={analyzedCount} tone="#3fcf8e" />
          <Kpi label="Skipped" value={skippedCount} />
          <Kpi label="Findings" value={findings.length} tone="#ffb357" />
          <Kpi label="Open cases" value={openCaseCount} tone="#b877d9" />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(260px, 0.45fr)', gap: 16, marginTop: 16 }}>
          <div style={panelStyle('#ffb357')}>
            <h3 style={sectionTitleStyle}>Recent findings</h3>
            {recentFindings.length ? recentFindings.map((finding) => (
              <OverviewRow key={finding.id ?? finding.title} title={`${finding.service ?? 'unknown'} - ${finding.title}`} meta={`${finding.metric_name} · ${finding.health_status}`} tone={finding.health_status === 'critical' ? '#f2495c' : '#ffb357'} />
            )) : <p style={styles.muted}>No findings returned for the last 24h.</p>}
          </div>
          <div style={panelStyle('#73bf69')}>
            <h3 style={sectionTitleStyle}>Findings by type</h3>
            {Object.entries(findingTypes).length ? Object.entries(findingTypes).map(([type, count]) => (
              <OverviewRow key={type} title={humanize(type)} meta={`${count} finding${count === 1 ? '' : 's'}`} tone="#73bf69" />
            )) : <p style={styles.muted}>No finding types available.</p>}
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 16, marginTop: 16 }}>
          <div style={panelStyle('#5794f2')}>
            <h3 style={sectionTitleStyle}>Execution history</h3>
            {recentRuns.length ? recentRuns.map((run) => (
              <OverviewRow key={run.id} title={`${run.service} / ${run.metric_name}`} meta={`${run.sample_count} samples · ${run.status}`} tone="#5794f2" />
            )) : <p style={styles.muted}>No analysis runs returned yet.</p>}
          </div>
          <div style={panelStyle('#b877d9')}>
            <h3 style={sectionTitleStyle}>Recent cases</h3>
            {recentCases.length ? recentCases.map((caseItem) => (
              <OverviewRow key={caseItem.id} title={`Case #${caseItem.id} - ${caseItem.case_title}`} meta={`${caseItem.case_status} · ${caseItem.investigation_status}`} tone="#b877d9" />
            )) : <p style={styles.muted}>No cases returned yet.</p>}
          </div>
        </div>
      </Card>
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
        <Kpi label="Failed" value={result.failed_jobs} tone={result.failed_jobs ? '#f2495c' : '#d8d9da'} />
      </div>
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
  return (
    <Card>
      <div style={styles.rowBetween}>
        <div>
          <h2 style={{ margin: 0 }}>Metric Plan Preview</h2>
          <p style={{ ...styles.muted, margin: '5px 0 0' }}>Review selected and excluded metric groups before scheduler execution exists.</p>
        </div>
        <span style={{ ...styles.chip, color: '#3fcf8e' }}>{result.planned_jobs} planned jobs</span>
      </div>
      {result.warnings.map((warning) => <div key={warning} style={{ ...styles.alert, marginTop: 12 }}>{warning}</div>)}
      <div style={{ ...styles.compactStats, marginTop: 16 }}>
        <Kpi label="Services resolved" value={result.scope_summary.services ?? 0} />
        <Kpi label="Namespaces resolved" value={result.scope_summary.namespaces ?? 0} />
        <Kpi label="Metrics discovered" value={result.metrics_discovered} />
        <Kpi label="Metrics selected" value={result.metrics_selected ?? result.metrics_matched} tone="#3fcf8e" />
        <Kpi label="Metrics excluded" value={result.metrics_excluded} tone="#ffb357" />
        <Kpi label="Budget limited" value={result.budget_limited_jobs ?? result.budget_limited} tone="#b877d9" />
      </div>
      {result.monitoring_summary?.concepts?.length ? (
        <div style={{ ...styles.infoNote, marginTop: 12 }}>
          Intent expanded to concepts: {result.monitoring_summary.concepts.map(humanize).join(', ')}
        </div>
      ) : null}
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
      {!rows.length ? (
        <div style={styles.emptyHero}>
          <p>No preview rows match the current filters.</p>
        </div>
      ) : (
        <div style={{ overflow: 'auto', marginTop: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '0.8fr 0.9fr 0.9fr 1fr 1fr 0.8fr 1.4fr 1fr 1fr 0.7fr 1.2fr 1.4fr', gap: 10, minWidth: 1480, fontSize: 12 }}>
            {['Status', 'Service', 'Namespace', 'Category', 'Concept', 'Type', 'Metric', 'Transform', 'Aggregation', 'Conf.', 'Reason', 'PromQL'].map((header) => <div key={header} style={styles.tableHeader}>{header}</div>)}
            {rows.map((item) => {
              const rowKey = `${item.service ?? 'unknown'}:${item.namespace ?? 'all'}:${item.metric_name}:${item.category ?? 'none'}`;
              const expanded = expandedMetric === rowKey;
              return (
                <React.Fragment key={rowKey}>
                  <div style={{ color: item.planned ? '#3fcf8e' : '#ffb357' }}>{item.planned ? 'Planned' : 'Excluded'}</div>
                  <div>{item.service ?? 'unknown'}</div>
                  <div>{item.namespace ?? 'all'}</div>
                  <div>{item.category ? humanize(item.category) : 'Unmatched'}</div>
                  <div>{item.concept ? humanize(item.concept) : 'Unmatched'}</div>
                  <div>{item.metric_type ?? 'unknown'}</div>
                  <button type="button" style={styles.tableRowButton} onClick={() => setExpandedMetric(expanded ? null : rowKey)}>{item.metric_name}</button>
                  <div>{humanize(item.transformation ?? 'raw')}</div>
                  <div>{humanize(item.aggregation ?? item.aggregation_strategy)}</div>
                  <div>{item.confidence.toFixed(2)}</div>
                  <div>{humanize(item.selection_reason ?? item.exclusion_reason ?? 'not selected')}</div>
                  <code style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.promql || '-'}</code>
                  {expanded && (
                    <div style={{ gridColumn: '1 / -1', ...styles.answerCard }}>
                      {item.planned
                        ? `${previewRowExplanation(item)}${item.matched_rule ? ` Matched ${item.matched_rule}.` : ''}`
                        : previewRowExplanation(item)}
                      <div style={styles.helperText}>Estimated series: {item.estimated_series_count}. Group by: {(item.group_by ?? []).join(', ') || 'service'}. Analysis window: {item.analysis_window}. Router/analyzer selection will still happen later per planned AnalysisRequest.</div>
                      {item.promql && <pre style={{ ...styles.pre, marginTop: 10 }}>{item.promql}</pre>}
                    </div>
                  )}
                </React.Fragment>
              );
            })}
          </div>
        </div>
      )}
    </Card>
  );
}

function OverviewRow({ title, meta, tone }: { title: string; meta: string; tone: string }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '12px minmax(0, 1fr)', gap: 10, alignItems: 'center', padding: '8px 0', borderBottom: '1px solid rgba(204, 204, 220, 0.08)' }}>
      <span style={{ width: 8, height: 8, borderRadius: 999, background: tone }} />
      <div>
        <div style={{ fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{title}</div>
        <div style={styles.helperText}>{meta}</div>
      </div>
    </div>
  );
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
