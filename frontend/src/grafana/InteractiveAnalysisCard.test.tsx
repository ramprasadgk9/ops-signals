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
  it('keeps the Grafana data source path as it was, and offers the connection path', () => {
    const props = renderCard();

    expect(screen.getByText('Data source')).toBeInTheDocument();
    expect(screen.queryByLabelText('Prometheus connection')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Cluster')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Query through'), { target: { value: 'connection' } });
    expect(props.setSource).toHaveBeenCalledWith('connection');
  });

  it('through a connection: picks the connection and lists its services and metrics', () => {
    const props = renderCard({ source: 'connection' });

    expect(screen.queryByText('Data source')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Prometheus connection'), { target: { value: 'team-a' } });
    expect(props.setConnectionId).toHaveBeenCalledWith('team-a');
    expect(document.querySelector('#ops-signals-services option')?.getAttribute('value')).toBe('checkout');
    expect(document.querySelector('#ops-signals-metrics option')?.getAttribute('value')).toBe('request_latency_p95');
  });

  it('asks for a cluster when the series is in several, and Run waits for it', () => {
    const props = renderCard({ source: 'connection', clusterOptions: ['eu', 'us'], ready: false });

    expect(screen.getByText(/This series is in 2 clusters; one is analysed per run\. Choose one to run\./)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run Analysis' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Cluster'), { target: { value: 'us' } });
    expect(props.setCluster).toHaveBeenCalledWith('us');
  });

  it('shows no Query through choice when the backend has no connections', () => {
    renderCard({ connections: [] });

    expect(screen.queryByLabelText('Query through')).not.toBeInTheDocument();
    expect(screen.getByText('Data source')).toBeInTheDocument();
  });
});
