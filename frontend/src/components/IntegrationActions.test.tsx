import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { DEMO_CSV_PATH, LoadDemoDataButton, SendTestAlertButton } from './IntegrationActions';
import { api } from '../api/queries';

vi.mock('../api/queries', () => ({
  api: {
    sendTestAlert: vi.fn(),
    runCsvUpload: vi.fn(),
  },
}));

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe('SendTestAlertButton', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('confirms a test alert that was accepted', async () => {
    vi.mocked(api.sendTestAlert).mockResolvedValue({ accepted: 1, duplicates: 0, resolved: 0, disabled: false, enrichment_ids: [5] });
    renderWithProviders(<SendTestAlertButton />);

    fireEvent.click(screen.getByRole('button', { name: 'Send test alert' }));

    expect(await screen.findByText(/Test alert sent/)).toBeInTheDocument();
    expect(api.sendTestAlert).toHaveBeenCalledTimes(1);
  });

  it('explains when enrichment is off', async () => {
    vi.mocked(api.sendTestAlert).mockResolvedValue({ accepted: 0, duplicates: 0, resolved: 0, disabled: true, enrichment_ids: [] });
    renderWithProviders(<SendTestAlertButton />);

    fireEvent.click(screen.getByRole('button', { name: 'Send test alert' }));

    expect(await screen.findByText(/Alert enrichment is off/)).toBeInTheDocument();
  });

  it('shows the server error instead of failing silently', async () => {
    vi.mocked(api.sendTestAlert).mockRejectedValue(new Error('Missing or invalid bearer token'));
    renderWithProviders(<SendTestAlertButton />);

    fireEvent.click(screen.getByRole('button', { name: 'Send test alert' }));

    expect(await screen.findByText('Could not send the test alert: Missing or invalid bearer token')).toBeInTheDocument();
  });
});

describe('LoadDemoDataButton', () => {
  afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it('uploads the bundled demo CSV through the normal CSV analysis endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('timestamp,metric_name,value\n', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    vi.mocked(api.runCsvUpload).mockResolvedValue({
      analysis_run_id: 'run-demo',
      file_name: 'demo-checkout-cpu.csv',
      provider: 'generic',
      source_type: 'csv',
      service: 'checkout',
      metric_name: 'cpu_usage',
      sample_count: 288,
      findings_count: 1,
    });
    renderWithProviders(<LoadDemoDataButton />);

    fireEvent.click(screen.getByRole('button', { name: 'Load demo data' }));

    expect(await screen.findByText(/Demo analysis complete for checkout \/ cpu_usage/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View findings →' })).toHaveAttribute('href', '/findings');
    expect(fetchMock).toHaveBeenCalledWith(`${import.meta.env.BASE_URL}${DEMO_CSV_PATH}`);
    const form = vi.mocked(api.runCsvUpload).mock.calls[0][0];
    expect(form.get('provider')).toBe('generic');
    expect(form.get('service')).toBe('checkout');
    expect(form.get('metric_name')).toBe('cpu_usage');
    expect((form.get('file') as File).name).toBe('demo-checkout-cpu.csv');
  });

  it('reports a missing demo file without calling the backend', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 404 })));
    renderWithProviders(<LoadDemoDataButton />);

    fireEvent.click(screen.getByRole('button', { name: 'Load demo data' }));

    expect(await screen.findByText('Could not load demo data: demo data file not found (404)')).toBeInTheDocument();
    expect(api.runCsvUpload).not.toHaveBeenCalled();
  });
});
