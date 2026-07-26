import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { OperationalMemoryPage } from './OperationalMemoryPage';
import { api } from '../api/queries';

vi.mock('../api/queries', () => ({
  api: {
    cases: vi.fn(),
    memoryStats: vi.fn(),
  },
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <OperationalMemoryPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const memoryStats = {
  generated_at: '2026-07-26T00:00:00Z',
  enabled: true,
  status: 'healthy',
  indexed_cases: 1,
  not_indexed_cases: 1,
  stale_cases: 0,
  error_cases: 0,
  total_cases: 2,
  source: 'ops_operational_cases.memory_status',
};

const baseCase = {
  id: 10,
  finding_id: 1,
  analysis_run_id: 'run-1',
  case_title: 'CPU usage behavior changed',
  case_status: 'open',
  finding_snapshot: {
    id: 1,
    service: 'checkout',
    metric_name: 'cpu_usage',
    title: 'CPU usage behavior changed',
    summary: 'CPU moved outside normal range',
    category: 'behavior_change',
    health_status: 'critical',
    importance_score: 0.9,
    investigation_priority: 0.9,
    signal_ids: [],
    comparison_json: {},
    created_at: '2026-07-26T00:00:00Z',
  },
  investigation_status: 'open',
  investigation_notes: [],
  root_cause_status: 'unknown',
  root_cause_verified: false,
  outcome_status: 'pending',
  memory_status: 'indexed',
  created_at: '2026-07-26T00:00:00Z',
  updated_at: '2026-07-26T01:00:00Z',
};

describe('OperationalMemoryPage', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('shows authoritative memory stats and indexed case inventory', async () => {
    vi.mocked(api.memoryStats).mockResolvedValue(memoryStats);
    vi.mocked(api.cases).mockResolvedValue([
      baseCase,
      { ...baseCase, id: 11, case_title: 'Disk saturation', memory_status: 'not_indexed' },
    ]);

    renderPage();

    expect(await screen.findByText('Operational Memory')).toBeInTheDocument();
    expect(screen.getByText('Indexed Cases')).toBeInTheDocument();
    expect(screen.getByText('CPU usage behavior changed')).toBeInTheDocument();
    expect(screen.queryByText('Disk saturation')).not.toBeInTheDocument();
    expect(api.cases).toHaveBeenCalledWith(200);
  });

  it('does not convert unavailable memory stats into zero counts', async () => {
    vi.mocked(api.memoryStats).mockResolvedValue({ ...memoryStats, status: 'unhealthy', indexed_cases: 4 });
    vi.mocked(api.cases).mockResolvedValue([]);

    renderPage();

    expect(await screen.findAllByText('Unavailable')).not.toHaveLength(0);
    expect(screen.getByText('Memory unavailable')).toBeInTheDocument();
  });
});
