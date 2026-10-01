import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { AlertsPage } from './AlertsPage';
import { api } from '../api/queries';
import type { AlertItem } from '../types';

vi.mock('../api/queries', () => ({
  api: {
    alerts: vi.fn(),
  },
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AlertsPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function alert(overrides: Partial<AlertItem> = {}): AlertItem {
  return {
    id: 1, source: 'alertmanager', alert_name: 'HighLatency', status: 'firing', service: 'checkout-api', severity: 'critical',
    summary: 'p95 above 300ms', starts_at: new Date().toISOString(), ends_at: null, received_at: new Date().toISOString(), labels: {},
    generator_url: null, analysis_status: 'completed', recommendation: null, notify_status: 'posted', finding_id: 7, case_id: 12,
    ...overrides,
  };
}

describe('AlertsPage', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('lists received alerts with their timeline and links', async () => {
    vi.mocked(api.alerts).mockResolvedValue([
      alert(),
      alert({ id: 2, alert_name: 'DiskFull', status: 'resolved', summary: 'DiskFull', finding_id: null, case_id: null }),
    ]);

    renderPage();

    expect(await screen.findByRole('heading', { name: 'Alerts' })).toBeInTheDocument();
    const panel = await screen.findByRole('region', { name: 'Received alerts' });
    expect(await within(panel).findByRole('figure', { name: /Alert timeline/ })).toBeInTheDocument();
    const rules = within(panel).getByLabelText('Alert rules');
    expect(within(rules).getByText('HighLatency')).toBeInTheDocument();
    expect(within(rules).getByRole('link', { name: 'linked to Case #12' })).toHaveAttribute('href', '/cases/12');
    expect(within(rules).getByText('DiskFull')).toBeInTheDocument();
    expect(within(rules).getByText('RESOLVED')).toBeInTheDocument();
  });

  it('shows an empty state before any alert arrives', async () => {
    vi.mocked(api.alerts).mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText(/No alerts in the last 24 hours/)).toBeInTheDocument();
  });
});
