import React from 'react';
import { useEffect, useMemo, useState } from 'react';
import { listAnalysisRuns, listMetrics, listServices, runBackendAnalysis } from './backendClient';
import { PanelPreview } from './PanelPreview';
import { Card, Field, styles } from './plainUi';
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
  { label: 'Local backend (:8000)', value: 'http://localhost:8000' },
  { label: 'Host backend from Docker', value: 'http://host.docker.internal:8000' },
];

export function PluginApp(_props: unknown) {
  const [target, setTarget] = useState<GrafanaQueryTarget>(defaultTarget);
  const [result, setResult] = useState<GrafanaAnalysisResult | null>(null);
  const [backendUrl, setBackendUrl] = useState('http://localhost:8000');
  const [services, setServices] = useState<string[]>([]);
  const [metrics, setMetrics] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [isLoadingContext, setIsLoadingContext] = useState(false);
  const [isRunning, setIsRunning] = useState(false);

  useEffect(() => {
    let active = true;
    setIsLoadingContext(true);
    setError('');

    Promise.all([listServices(backendUrl), listAnalysisRuns(backendUrl)])
      .then(([nextServices]) => {
        if (!active) return;
        setServices(nextServices);
      })
      .catch(() => {
        if (active) setError('Failed to load plugin context from the Ops Signals backend.');
      })
      .finally(() => {
        if (active) setIsLoadingContext(false);
      });

    return () => {
      active = false;
    };
  }, [backendUrl]);

  useEffect(() => {
    let active = true;
    setMetrics([]);
    if (!target.service) return;

    listMetrics(backendUrl, target.service)
      .then((nextMetrics) => {
        if (active) setMetrics(nextMetrics);
      })
      .catch(() => {
        if (active) setError(`Failed to load metrics for ${target.service}.`);
      });

    return () => {
      active = false;
    };
  }, [backendUrl, target.service]);

  const backendReady = useMemo(() => services.length > 0 || metrics.length > 0, [metrics.length, services.length]);
  const ready = Boolean(target.service && target.metric);
  const buttonStyle = ready && !isRunning ? styles.button : { ...styles.button, ...styles.buttonDisabled };

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

      <Card>
        <div style={styles.toolbar}>
          <Field label="Data source">
            <select style={styles.input} value={target.datasource} onChange={(event) => setTarget((current) => ({ ...current, datasource: event.target.value }))}>
              <option value="Prometheus">Prometheus</option>
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
            <select
              style={styles.input}
              value={target.service}
              onChange={(event) => setTarget((current) => ({ ...current, service: event.target.value, metric: '' }))}
            >
              <option value="" />
              {services.map((service) => (
                <option key={service} value={service}>
                  {service}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Metric">
            <select
              style={styles.input}
              value={target.metric}
              onChange={(event) => setTarget((current) => ({ ...current, metric: event.target.value }))}
              disabled={!target.service}
            >
              <option value="" />
              {metrics.map((metric) => (
                <option key={metric} value={metric}>
                  {metric}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Time range">
            <select style={styles.input} value="last_14_days" onChange={() => undefined}>
              <option value="last_14_days">Last 14 days</option>
            </select>
          </Field>
          <button
            type="button"
            style={buttonStyle}
            onClick={async () => {
              if (!ready) return;
              setIsRunning(true);
              setError('');
              try {
                const nextTarget = { ...target, datasource: 'Prometheus' };
                const backendResult = await runBackendAnalysis(backendUrl, {
                  datasource: nextTarget.datasource,
                  service: nextTarget.service,
                  metric: nextTarget.metric,
                  from: nextTarget.timeRange.from,
                  to: nextTarget.timeRange.to,
                });
                setTarget(nextTarget);
                setResult(backendResult);
              } catch {
                setError('Analysis request failed. Confirm the backend is reachable at the configured URL.');
              } finally {
                setIsRunning(false);
              }
            }}
            disabled={!ready || isRunning}
          >
            {isRunning ? 'Running...' : 'Run Analysis'}
          </button>
        </div>
      </Card>

      <PanelPreview result={result} backendUrl={backendUrl} />
    </main>
  );
}
