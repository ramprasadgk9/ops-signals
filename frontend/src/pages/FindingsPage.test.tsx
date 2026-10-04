import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { FindingsPage } from './FindingsPage';
import { api } from '../api/queries';
import type { Finding } from '../types';

vi.mock('../api/queries', () => ({
  api: {
    findings: vi.fn(),
    overviewSummary: vi.fn(),
    signalsByRunIds: vi.fn(),
    getFinding: vi.fn(),
    analysisRun: vi.fn(),
    timeseries: vi.fn(),
    alerts: vi.fn(),
  },
}));

const finding: Finding = {
  id: 7,
  service: 'checkout-api',
  metric_name: 'latency_p95',
  title: 'Latency shift on checkout-api',
  summary: 'p95 up',
  category: 'behavior_change',
  health_status: 'critical',
  importance_score: 0.9,
  investigation_priority: 1,
  signal_ids: [],
  comparison_json: {},
  created_at: '2026-09-20T00:00:00Z',
};

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.search}</div>;
}

function renderAt(url: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/findings" element={<><FindingsPage /><LocationProbe /></>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('FindingsPage deep link', () => {
  beforeEach(() => {
    // An older finding: outside the 24h list, which is exactly why the deep link fetches it itself.
    vi.mocked(api.findings).mockResolvedValue([]);
    vi.mocked(api.overviewSummary).mockResolvedValue({
      generated_at: '2026-09-26T00:00:00Z',
      window: '24h',
      active_findings: 0,
      open_cases: 0,
      behavior_changes: 0,
      impacted_services: 0,
      memory_items: 0,
      severity_trend: [],
      category_breakdown: [],
    });
    vi.mocked(api.alerts).mockResolvedValue([]);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('opens the linked finding and drops the parameter when the drawer closes', async () => {
    vi.mocked(api.getFinding).mockResolvedValue(finding);

    renderAt('/findings?finding=7');

    expect(await screen.findByRole('heading', { name: 'Latency shift on checkout-api' })).toBeInTheDocument();
    expect(api.getFinding).toHaveBeenCalledWith(7);

    fireEvent.keyDown(screen.getByRole('presentation'), { key: 'Escape' });
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(/^$/));
  });

  it('says so when the linked finding does not exist, and still shows the list', async () => {
    vi.mocked(api.getFinding).mockRejectedValue(new Error('404'));

    renderAt('/findings?finding=999');

    expect(await screen.findByText('Finding #999 could not be found.')).toBeInTheDocument();
    expect(screen.getByText('No findings returned for this window.')).toBeInTheDocument();
  });

  it('ignores a malformed finding parameter', async () => {
    renderAt('/findings?finding=abc');

    expect(await screen.findByText('No findings returned for this window.')).toBeInTheDocument();
    expect(api.getFinding).not.toHaveBeenCalled();
  });
});

describe('FindingsPage category legend', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('explains each category in plain words', async () => {
    vi.mocked(api.findings).mockResolvedValue([]);
    vi.mocked(api.alerts).mockResolvedValue([]);
    vi.mocked(api.overviewSummary).mockResolvedValue({
      generated_at: '2026-09-26T00:00:00Z',
      window: '24h',
      active_findings: 3,
      open_cases: 0,
      behavior_changes: 1,
      impacted_services: 1,
      memory_items: 0,
      severity_trend: [],
      category_breakdown: [
        { category: 'data_quality', count: 679 },
        { category: 'behavior_change', count: 168 },
        { category: 'unusual_activity', count: 108 },
      ],
    });

    renderAt('/findings');

    expect(await screen.findByText('Data Quality')).toBeInTheDocument();
    expect(screen.getByText('The metric stopped reporting or froze at one value')).toBeInTheDocument();
    expect(screen.getByText('The metric moved to a new normal level, or is steadily trending')).toBeInTheDocument();
    expect(screen.getByText('Short spikes or dips that don’t fit the usual pattern')).toBeInTheDocument();
  });
});

describe('FindingsPage cluster filter', () => {
  const inCluster = (id: number, cluster: string | null): Finding => ({ ...finding, id, cluster, title: `Latency shift in ${cluster ?? 'single cluster'}` });

  beforeEach(() => {
    vi.mocked(api.overviewSummary).mockResolvedValue({
      generated_at: '2026-09-26T00:00:00Z',
      window: '24h',
      active_findings: 2,
      open_cases: 0,
      behavior_changes: 0,
      impacted_services: 1,
      memory_items: 0,
      severity_trend: [],
      category_breakdown: [],
    });
    vi.mocked(api.alerts).mockResolvedValue([]);
    vi.mocked(api.signalsByRunIds).mockResolvedValue([]);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('shows each cluster on its finding and filters by cluster', async () => {
    vi.mocked(api.findings).mockResolvedValue([inCluster(1, 'eu'), inCluster(2, 'us')]);

    renderAt('/findings');

    expect(await screen.findByText('checkout-api · latency_p95 · eu')).toBeInTheDocument();
    expect(screen.getByText('checkout-api · latency_p95 · us')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'us' }));

    await waitFor(() => expect(screen.queryByText('Latency shift in eu')).not.toBeInTheDocument());
    expect(screen.getByText('Latency shift in us')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('cluster=us');

    fireEvent.click(screen.getByRole('button', { name: 'All clusters' }));
    expect(await screen.findByText('Latency shift in eu')).toBeInTheDocument();
  });

  it('hides the cluster filter for single-cluster data', async () => {
    vi.mocked(api.findings).mockResolvedValue([inCluster(1, null)]);

    renderAt('/findings');

    expect(await screen.findByText('checkout-api · latency_p95')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'All clusters' })).not.toBeInTheDocument();
  });
});
