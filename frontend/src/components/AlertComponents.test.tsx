import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { AlertRow, LinkedAlerts, alertsByFinding } from './AlertComponents';
import { api } from '../api/queries';
import type { AlertItem } from '../types';

vi.mock('../api/queries', () => ({
  api: {
    alerts: vi.fn(),
  },
}));

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  );
}

const base: AlertItem = {
  id: 1,
  source: 'alertmanager',
  alert_name: 'HighLatency',
  status: 'firing',
  service: 'checkout-api',
  severity: null,
  summary: 'p95 above 300ms',
  starts_at: '2026-09-26T00:00:00Z',
  ends_at: null,
  received_at: '2026-09-26T00:00:00Z',
  labels: {},
  generator_url: null,
  analysis_status: null,
  recommendation: null,
  notify_status: null,
  finding_id: 7,
  case_id: null,
};

describe('LinkedAlerts', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('shows one badge per alert linked to the finding', async () => {
    vi.mocked(api.alerts).mockResolvedValue([base, { ...base, id: 2, alert_name: 'ErrorBudgetBurn', status: 'resolved' }]);

    renderWithProviders(<LinkedAlerts findingId={7} />);

    expect(await screen.findByText('Alert: HighLatency')).toBeInTheDocument();
    expect(screen.getByText('Alert: ErrorBudgetBurn (resolved)')).toBeInTheDocument();
    expect(api.alerts).toHaveBeenCalledWith({ finding_id: 7, limit: 10 });
  });

  it('renders nothing when no alert is linked or the lookup fails', async () => {
    vi.mocked(api.alerts).mockResolvedValueOnce([]);
    const { container, unmount } = renderWithProviders(<LinkedAlerts findingId={7} />);
    await waitFor(() => expect(api.alerts).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
    unmount();

    vi.mocked(api.alerts).mockRejectedValueOnce(new Error('401'));
    const failed = renderWithProviders(<LinkedAlerts findingId={8} />);
    await waitFor(() => expect(api.alerts).toHaveBeenCalledTimes(2));
    expect(failed.container).toBeEmptyDOMElement();
  });

  it('does not query at all without a finding id (behavior-based cases)', () => {
    const { container } = renderWithProviders(<LinkedAlerts findingId={null} />);
    expect(container).toBeEmptyDOMElement();
    expect(api.alerts).not.toHaveBeenCalled();
  });
});

describe('AlertRow', () => {
  it('links an alert to its finding when no case exists yet', () => {
    renderWithProviders(<AlertRow alert={base} />);
    expect(screen.getByRole('link', { name: 'linked to Finding #7' })).toHaveAttribute('href', '/findings?finding=7');
  });

  it('links to the case when one exists', () => {
    renderWithProviders(<AlertRow alert={{ ...base, case_id: 12 }} />);
    expect(screen.getByRole('link', { name: 'linked to Case #12' })).toHaveAttribute('href', '/cases/12');
  });
});

describe('alertsByFinding', () => {
  it('keeps the newest alert per finding and skips unlinked ones', () => {
    const newest = { ...base, id: 3 };
    const older = { ...base, id: 1 };
    const unlinked = { ...base, id: 2, finding_id: null };
    const map = alertsByFinding([newest, unlinked, older]);
    expect(map.size).toBe(1);
    expect(map.get(7)?.id).toBe(3);
  });
});

describe('AlertRow labels', () => {
  it('marks alerts sent with "Send test alert" as tests', () => {
    renderWithProviders(<AlertRow alert={{ ...base, source: 'test', alert_name: 'OpsSignalsTestAlert', finding_id: null }} />);
    expect(screen.getByText(/^Test alert · Firing/)).toBeInTheDocument();
  });
});
