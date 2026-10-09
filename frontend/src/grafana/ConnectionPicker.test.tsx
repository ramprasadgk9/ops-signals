import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { testPrometheusConnection } from './backendClient';
import { ConnectionPicker } from './PluginApp';

// PluginApp's Prometheus query path imports @grafana/* (only loadable inside Grafana).
vi.mock('./grafanaPrometheus', () => ({}));
vi.mock('./prometheusFrameNormalizer', () => ({}));
vi.mock('./backendClient', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./backendClient')>()),
  testPrometheusConnection: vi.fn(),
}));
const testConnection = vi.mocked(testPrometheusConnection);

const CONNECTIONS = [
  { id: 'default', name: 'Default Prometheus', configured: true, is_default: true },
  { id: 'team-b', name: 'Team B (Mimir)', configured: false },
];

describe('ConnectionPicker', () => {
  beforeEach(() => {
    testConnection.mockReset();
  });

  it('lists the connections, marks unconfigured ones, and reports a picked one', () => {
    const onChange = vi.fn();
    render(<ConnectionPicker backendUrl="http://backend" connections={CONNECTIONS} connectionId="default" onChange={onChange} />);

    expect(screen.getByRole('option', { name: 'Team B (Mimir) (not configured)' })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Prometheus connection'), { target: { value: 'team-b' } });

    expect(onChange).toHaveBeenCalledWith('team-b');
  });

  it('tests the connection and says whether it answered', async () => {
    testConnection.mockResolvedValueOnce({ available: true, latency_ms: 42.4, message: 'ok' }).mockResolvedValueOnce({ available: false, message: 'connection refused' });
    render(<ConnectionPicker backendUrl="http://backend" connections={CONNECTIONS} connectionId="team-b" onChange={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Test' }));
    expect(await screen.findByText('Connected · 42 ms')).toBeInTheDocument();
    expect(testConnection).toHaveBeenCalledWith('http://backend', 'team-b');

    fireEvent.click(screen.getByRole('button', { name: 'Test' }));
    expect(await screen.findByText('connection refused')).toBeInTheDocument();
  });
});
