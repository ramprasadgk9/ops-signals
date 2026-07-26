import React from 'react';
import { useEffect, useMemo, useState } from 'react';
import { runPrometheusSampleAnalysis } from './backendClient';
import { buildTimeRange, calculateIntervalMs, createRelativeTimeRange, formatDateTimeLocal, parseDateTimeLocal, readGrafanaTimeRange } from './grafanaTimeRange';
import {
  discoverMetricNames,
  discoverServiceValues,
  listPrometheusDatasources,
  queryPrometheusDatasource,
  type PrometheusDatasourceRef,
} from './grafanaPrometheus';
import { PanelPreview } from './PanelPreview';
import { Card, Field, styles } from './plainUi';
import { buildMetricQuery, type MetricMode } from './prometheusQueryBuilder';
import { normalizePrometheusFrames } from './prometheusFrameNormalizer';
import type { GrafanaAnalysisResult, GrafanaQueryTarget } from './contracts';

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

export function PluginApp(_props: unknown) {
  const defaultBackendUrl = import.meta.env.VITE_OPS_SIGNALS_BACKEND_URL ?? 'http://localhost:8002';
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
  const [metrics, setMetrics] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [stage, setStage] = useState('');
  const [isLoadingContext, setIsLoadingContext] = useState(false);
  const [isRunning, setIsRunning] = useState(false);

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
    setIsLoadingContext(true);
    setError('');

    Promise.all([
      discoverServiceValues(selectedPrometheusUid, serviceLabel),
      discoverMetricNames(selectedPrometheusUid),
    ])
      .then(([nextServices, nextMetrics]) => {
        if (!active) return;
        setServices(nextServices);
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
  }, [selectedPrometheusUid, serviceLabel]);

  useEffect(() => {
    const refreshRange = () => setTimeRange(readGrafanaTimeRange());
    window.addEventListener('popstate', refreshRange);
    return () => window.removeEventListener('popstate', refreshRange);
  }, []);

  useEffect(() => {
    setTimeFromInput(formatDateTimeLocal(timeRange.from));
    setTimeToInput(formatDateTimeLocal(timeRange.to));
  }, [timeRange]);

  const selectedDatasource = useMemo(
    () => prometheusDatasources.find((datasource) => datasource.uid === selectedPrometheusUid),
    [prometheusDatasources, selectedPrometheusUid]
  );
  const backendReady = useMemo(() => Boolean(backendUrl), [backendUrl]);
  const ready = Boolean(selectedPrometheusUid && target.service && target.metric);
  const timeRangeValid = timeRange.from.getTime() < timeRange.to.getTime();
  const buttonStyle = ready && !isRunning ? styles.button : { ...styles.button, ...styles.buttonDisabled };

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

      <Card>
        <div style={styles.toolbar}>
          <Field label="Data source">
            <select
              style={styles.input}
              value={selectedPrometheusUid}
              onChange={(event) => {
                setSelectedPrometheusUid(event.target.value);
                setResult(null);
              }}
            >
              <option value="">{prometheusDatasources.length ? 'Select Prometheus' : 'No Prometheus datasource'}</option>
              {prometheusDatasources.map((datasource) => (
                <option key={datasource.uid} value={datasource.uid}>
                  {datasource.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Ops Signals backend">
            <select
              style={styles.input}
              value={backendUrl}
              onChange={(event) => {
                setBackendUrl(event.target.value);
                setResult(null);
                setTarget((current) => ({ ...current, service: '', metric: '' }));
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
              value={target.service}
              placeholder={`Value for label "${serviceLabel}"`}
              onChange={(event) => setTarget((current) => ({ ...current, service: event.target.value }))}
            />
            <datalist id="ops-signals-services">
              {services.map((service) => (
                <option key={service} value={service} />
              ))}
            </datalist>
          </Field>
          <Field label="Metric">
            <input
              style={styles.input}
              list="ops-signals-metrics"
              value={target.metric}
              placeholder={metricMode === 'metric' ? 'Metric name' : 'PromQL expression'}
              onChange={(event) => setTarget((current) => ({ ...current, metric: event.target.value }))}
            />
            <datalist id="ops-signals-metrics">
              {metrics.map((metric) => (
                <option key={metric} value={metric} />
              ))}
            </datalist>
          </Field>
          <Field label="Mode">
            <select style={styles.input} value={metricMode} onChange={(event) => setMetricMode(event.target.value as MetricMode)}>
              <option value="metric">Metric</option>
              <option value="promql">PromQL expression</option>
            </select>
          </Field>
          <Field label="Service label">
            <input style={styles.input} value={serviceLabel} onChange={(event) => setServiceLabel(event.target.value)} />
          </Field>
          <Field label="Time range">
            <div style={{ display: 'grid', gap: 8 }}>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {timePresets.map((preset) => (
                  <button key={preset.label} type="button" style={{ ...styles.chip, background: 'transparent', color: 'inherit', cursor: 'pointer' }} onClick={() => applyPreset(preset.hours)}>
                    {preset.label}
                  </button>
                ))}
              </div>
              <input style={{ ...styles.input, ...styles.inputReadOnly }} value={timeRange.display} readOnly />
              <input
                style={styles.input}
                type="datetime-local"
                value={timeFromInput}
                onChange={(event) => setTimeFromInput(event.target.value)}
              />
              <input
                style={styles.input}
                type="datetime-local"
                value={timeToInput}
                onChange={(event) => setTimeToInput(event.target.value)}
              />
              <button type="button" style={styles.button} onClick={applyCustomRange}>
                Apply custom range
              </button>
              <div style={styles.helperText}>Use quick presets for testing, or enter a custom local start and end time directly here.</div>
            </div>
          </Field>
          <button
            type="button"
            style={ready && timeRangeValid && !isRunning ? styles.button : { ...styles.button, ...styles.buttonDisabled }}
            onClick={async () => {
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
            disabled={!ready || !timeRangeValid || isRunning}
          >
            {isRunning ? 'Running...' : 'Run Analysis'}
          </button>
        </div>
      </Card>

      <PanelPreview result={result} backendUrl={backendUrl} />
    </main>
  );
}
