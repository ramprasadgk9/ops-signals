import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { InteractiveAnalysisCard, type InteractiveCardProps } from './PluginApp';

// PluginApp's Prometheus query path imports @grafana/* (only loadable inside Grafana).
vi.mock('./grafanaPrometheus', () => ({}));
vi.mock('./prometheusFrameNormalizer', () => ({}));

const CONNECTIONS = [
  { id: 'local', name: 'Local Prometheus', configured: true, is_default: true, cluster_label: 'cluster' },
  { id: 'team-a', name: 'Mimir team-a (eu, us)', configured: true, cluster_label: 'cluster' },
];

function renderCard(overrides: Partial<InteractiveCardProps> = {}) {
  const props: InteractiveCardProps = {
    source: 'grafana', setSource: vi.fn(), connections: CONNECTIONS, connectionId: 'local', setConnectionId: vi.fn(),
    connectionServices: ['checkout'], connectionMetrics: ['request_latency_p95'], clusterOptions: [], cluster: '', setCluster: vi.fn(),
    prometheusDatasources: [{ uid: 'prom', name: 'Prometheus' }] as InteractiveCardProps['prometheusDatasources'], selectedPrometheusUid: 'prom', setSelectedPrometheusUid: vi.fn(),
    backendUrl: 'http://backend', setBackendUrl: vi.fn(), target: { datasource: 'prom', service: 'checkout', metric: 'request_latency_p95', timeRange: { from: '', to: '' } }, setTarget: vi.fn(),
    services: ['grafana-service'], metrics: ['grafana_metric'], metricMode: 'metric', setMetricMode: vi.fn(), serviceLabel: 'service', setServiceLabel: vi.fn(),
    timeRange: { from: new Date('2026-10-08T00:00:00Z'), to: new Date('2026-10-09T00:00:00Z'), display: '24h' } as InteractiveCardProps['timeRange'],
    timeFromInput: '', setTimeFromInput: vi.fn(), timeToInput: '', setTimeToInput: vi.fn(), applyPreset: vi.fn(), applyCustomRange: vi.fn(),
    ready: true, timeRangeValid: true, isRunning: false, onClearResult: vi.fn(), onRun: vi.fn(async () => undefined),
    ...overrides,
  };
  render(<InteractiveAnalysisCard {...props} />);
  return props;
}

describe('InteractiveAnalysisCard query source', () => {
  it('reads from the Grafana data source by default, and offers the connection path', () => {
    const props = renderCard();

    expect(screen.getByRole('radio', { name: 'Grafana data source' })).toBeChecked();
    expect(screen.getByLabelText('Data source')).toBeEnabled();
    expect(screen.getByLabelText('Prometheus connection')).toBeDisabled();
    expect(screen.queryByLabelText('Cluster')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('radio', { name: 'Ops Signals connection' }));
    expect(props.setSource).toHaveBeenCalledWith('connection');
  });

  it('through a connection: picks the connection and lists its services and metrics', () => {
    const props = renderCard({ source: 'connection' });

    expect(screen.getByRole('radio', { name: 'Ops Signals connection' })).toBeChecked();
    expect(screen.getByLabelText('Data source')).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Prometheus connection'), { target: { value: 'team-a' } });
    expect(props.setConnectionId).toHaveBeenCalledWith('team-a');
    expect(document.querySelector('#ops-signals-services option')?.getAttribute('value')).toBe('checkout');
    expect(document.querySelector('#ops-signals-metrics option')?.getAttribute('value')).toBe('request_latency_p95');
  });

  it('asks for a cluster when the series is in several, and Run waits for it', () => {
    const props = renderCard({ source: 'connection', clusterOptions: ['eu', 'us'], ready: false });

    expect(screen.getByText(/This series is in 2 clusters; one is analysed per run\. Choose one to run\./)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run Analysis' })).toBeDisabled();
    expect(screen.getByText('Choose a cluster to run.')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Cluster'), { target: { value: 'us' } });
    expect(props.setCluster).toHaveBeenCalledWith('us');
  });

  it('shows no read-from choice when the backend has no connections', () => {
    renderCard({ connections: [] });

    expect(screen.queryByRole('radio')).not.toBeInTheDocument();
    expect(screen.getByText('Grafana data source')).toBeInTheDocument();
    expect(screen.getByLabelText('Data source')).toBeEnabled();
  });
});

describe('InteractiveAnalysisCard form', () => {
  it('says what is missing under a disabled Run Analysis', () => {
    renderCard({ selectedPrometheusUid: '', target: { datasource: '', service: '', metric: '', timeRange: { from: '', to: '' } }, ready: false });

    expect(screen.getByRole('button', { name: 'Run Analysis' })).toBeDisabled();
    expect(screen.getByText('Choose a data source, enter a service and enter a metric to run.')).toBeInTheDocument();
  });

  it('shows no reason once the form is ready', () => {
    renderCard();

    expect(screen.getByRole('button', { name: 'Run Analysis' })).toBeEnabled();
    expect(screen.queryByText(/to run\.$/)).not.toBeInTheDocument();
  });

  it('keeps the service label out of the way until "change" is clicked', () => {
    const props = renderCard();

    expect(screen.queryByLabelText('Service label')).not.toBeInTheDocument();
    expect(screen.getByText('service', { selector: 'strong' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Change service label' }));
    fireEvent.change(screen.getByLabelText('Service label'), { target: { value: 'job' } });
    expect(props.setServiceLabel).toHaveBeenCalledWith('job');
  });

  it('opens the service label when it is empty, since services can only be looked up with one', () => {
    renderCard({ serviceLabel: '' });

    expect(screen.getByLabelText('Service label')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'done' })).toBeDisabled();
  });

  it('switches between a metric name and a PromQL expression', () => {
    const props = renderCard();

    expect(screen.getByRole('button', { name: 'Metric', pressed: true })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'PromQL' }));
    expect(props.setMetricMode).toHaveBeenCalledWith('promql');
  });

  it('highlights the preset the range matches and applies a custom range as it changes', () => {
    const props = renderCard({ timeFromInput: '2026-10-08T00:00', timeToInput: '2026-10-09T00:00' });

    expect(screen.getByRole('button', { name: 'Last 24h', pressed: true })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Custom…' }));
    expect(screen.queryByRole('button', { name: 'Apply custom range' })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-10-08T06:00' } });
    expect(props.setTimeFromInput).toHaveBeenCalledWith('2026-10-08T06:00');
    expect(props.applyCustomRange).toHaveBeenCalledWith('2026-10-08T06:00', '2026-10-09T00:00');
    fireEvent.click(screen.getByRole('button', { name: 'Last 1h' }));
    expect(props.applyPreset).toHaveBeenCalledWith(1);
  });

  it('keeps the backend and API token behind "change" next to the backend line', () => {
    const props = renderCard();

    expect(screen.getByText(/Backend: backend/)).toBeInTheDocument();
    expect(screen.queryByText('Ops Signals backend')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Change backend' }));
    expect(screen.getByText('Ops Signals backend')).toBeInTheDocument();
    expect(screen.getByText('API token (optional)')).toBeInTheDocument();
    fireEvent.change(screen.getByDisplayValue('Grafana stack backend (:8002)'), { target: { value: 'http://localhost:8001' } });
    expect(props.setBackendUrl).toHaveBeenCalledWith('http://localhost:8001');
  });
});
