import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { IntegrationsPage } from './IntegrationsPage';
import { api } from '../api/queries';
import type { AlertItem, IngestionStatus } from '../types';

vi.mock('../api/queries', () => ({
  api: {
    ingestionStatus: vi.fn(),
    alerts: vi.fn(),
    otlpStatus: vi.fn(),
    sendTestAlert: vi.fn(),
    runCsvUpload: vi.fn(),
  },
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <IntegrationsPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const status: IngestionStatus = {
  generated_at: '2026-09-26T00:00:00Z',
  has_any_data: true,
  sources: {
    otlp: { endpoint_path: '/api/otlp/v1/metrics', last_received_at: null },
    alertmanager: { endpoint_path: '/api/integrations/alertmanager', enabled: true, token_required: true, last_received_at: new Date().toISOString(), received_24h: 2 },
    prometheus: { configured: false },
  },
};

const otlpStatus = {
  endpoint_path: '/api/otlp/v1/metrics',
  points_received_total: 0,
  points_rejected_total: {},
  backlog_size: 0,
  last_analysis_cycle_duration_seconds: 0,
  last_analysis_cycle_groups_processed: 0,
};

function alert(overrides: Partial<AlertItem> = {}): AlertItem {
  return {
    id: 1,
    source: 'alertmanager',
    alert_name: 'HighLatency',
    status: 'firing',
    service: 'checkout-api',
    severity: 'critical',
    summary: 'p95 above 300ms',
    starts_at: '2026-09-26T00:00:00Z',
    ends_at: null,
    received_at: new Date().toISOString(),
    labels: {},
    generator_url: null,
    analysis_status: 'completed',
    recommendation: null,
    notify_status: 'posted',
    finding_id: 7,
    case_id: 12,
    ...overrides,
  };
}

describe('IntegrationsPage', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('shows every source with its endpoint, status and recent alerts', async () => {
    vi.mocked(api.ingestionStatus).mockResolvedValue(status);
    vi.mocked(api.otlpStatus).mockResolvedValue(otlpStatus);
    vi.mocked(api.alerts).mockResolvedValue([
      alert(),
      alert({ id: 2, alert_name: 'DiskFull', status: 'resolved', summary: 'DiskFull', finding_id: null, case_id: null }),
    ]);

    renderPage();

    expect(await screen.findByRole('heading', { name: 'Integrations' })).toBeInTheDocument();
    expect(await screen.findByText('Send metrics via OTLP')).toBeInTheDocument();
    expect(screen.getByText('Connect Alertmanager')).toBeInTheDocument();
    expect(screen.getByText('2 alerts received in the last 24h')).toBeInTheDocument();
    // The receiver needs a token here, so the snippet shows where it goes.
    expect(screen.getByText(/credentials: <receiver token>/)).toBeInTheDocument();
    expect(screen.queryByText(/Alert enrichment is off/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send test alert' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Load demo data' })).toBeInTheDocument();
    // The OTLP tile already shows the endpoint, so the activity card leaves it out.
    expect(await screen.findByText('OTLP Ingestion Activity')).toBeInTheDocument();
    expect(screen.getAllByText(`${window.location.origin}/api/otlp/v1/metrics`)).toHaveLength(1);

    const alertsPanel = await screen.findByRole('region', { name: 'Alerts' });
    expect(await within(alertsPanel).findByRole('figure', { name: /Alert timeline/ })).toBeInTheDocument();
    const rules = within(alertsPanel).getByLabelText('Alert rules');
    expect(within(rules).getByText('HighLatency')).toBeInTheDocument();
    expect(within(rules).getByRole('link', { name: 'linked to Case #12' })).toHaveAttribute('href', '/cases/12');
    expect(within(rules).getByText('DiskFull')).toBeInTheDocument();
    expect(within(rules).getByText('RESOLVED')).toBeInTheDocument();
  });

  it('shows an empty state before any alert arrives', async () => {
    vi.mocked(api.ingestionStatus).mockResolvedValue(status);
    vi.mocked(api.otlpStatus).mockResolvedValue(otlpStatus);
    vi.mocked(api.alerts).mockResolvedValue([]);

    renderPage();

    expect(await screen.findByText(/No alerts in the last 24 hours/)).toBeInTheDocument();
  });

  it('keeps the OTLP card and alert list usable when the status call fails', async () => {
    vi.mocked(api.ingestionStatus).mockRejectedValue(new Error('network'));
    vi.mocked(api.otlpStatus).mockResolvedValue(otlpStatus);
    vi.mocked(api.alerts).mockResolvedValue([alert()]);

    renderPage();

    expect(await screen.findByText(/Could not load integration status/)).toBeInTheDocument();
    // Without the tiles, the card is the one place left that shows the endpoint.
    expect(await screen.findByText('OTLP Metrics Ingestion')).toBeInTheDocument();
    expect(screen.getByText(`${window.location.origin}/api/otlp/v1/metrics`)).toBeInTheDocument();
    expect(await screen.findAllByText('HighLatency')).toHaveLength(2);
  });
});
