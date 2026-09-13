import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ValidateDataPage } from './ValidateDataPage';
import { api } from '../api/queries';

vi.mock('../api/queries', () => ({
  api: {
    capabilities: vi.fn(),
    prometheusConnections: vi.fn(),
    prometheusLabelValues: vi.fn(),
    runCsvValidation: vi.fn(),
    testPrometheusConnection: vi.fn(),
    previewPrometheus: vi.fn(),
    runPrometheusAnalysis: vi.fn(),
  },
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ValidateDataPage />
    </QueryClientProvider>
  );
}

describe('ValidateDataPage source modes', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('switches between CSV upload and direct Prometheus controls', async () => {
    vi.mocked(api.capabilities).mockResolvedValue([]);
    vi.mocked(api.prometheusConnections).mockResolvedValue({
      connections: [{ id: 'default', name: 'Default Prometheus', base_url: 'http://prometheus:9090', configured: true }],
    });
    vi.mocked(api.prometheusLabelValues).mockImplementation(async (label: string) => ({
      connection_id: 'default',
      label,
      values: label === 'service' ? ['ruptures-lab', 'trend-lab'] : ['cpu_usage', 'ops_signal_lab_value'],
    }));

    renderPage();

    expect(await screen.findByRole('tab', { name: 'CSV Upload' })).toBeInTheDocument();
    expect(screen.getByText('Choose CSV File')).toBeInTheDocument();
    expect(screen.queryByText('Direct Prometheus')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: 'Prometheus' }));

    expect(await screen.findByText('Direct Prometheus')).toBeInTheDocument();
    expect(screen.getByLabelText('PromQL')).toBeInTheDocument();
    expect(screen.getAllByText('Last 24 hours').length).toBeGreaterThan(0);
    expect(screen.getByText('Preview Data')).toBeInTheDocument();
    expect(api.prometheusLabelValues).toHaveBeenCalledWith('service', 'default');
    expect(api.prometheusLabelValues).toHaveBeenCalledWith('__name__', 'default');
    expect(screen.queryByText('Choose CSV File')).not.toBeInTheDocument();
  });

  it('shows the expected CSV columns for the selected provider and updates when the provider changes', async () => {
    vi.mocked(api.capabilities).mockResolvedValue([]);
    vi.mocked(api.prometheusConnections).mockResolvedValue({ connections: [] });
    vi.mocked(api.prometheusLabelValues).mockResolvedValue({ connection_id: 'default', label: 'service', values: [] });

    renderPage();

    expect(await screen.findByText(/Expected columns for prometheus/)).toBeInTheDocument();
    expect(screen.getByText(/timestamp,metric,value/)).toBeInTheDocument();

    fireEvent.mouseDown(screen.getByText('Prometheus CSV'));
    fireEvent.click(await screen.findByRole('option', { name: 'Datadog CSV' }));

    expect(await screen.findByText(/Expected columns for datadog/)).toBeInTheDocument();
    expect(screen.getByText(/ts_epoch_ms,metric_name,value/)).toBeInTheDocument();
  });
});
