import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { OverviewPage } from './OverviewPage';
import { api } from '../api/queries';

vi.mock('../api/queries', () => ({
  api: {
    findings: vi.fn(),
    cases: vi.fn(),
    behaviorFindings: vi.fn(),
    overviewSummary: vi.fn(),
    memoryStats: vi.fn(),
  },
}));

function renderOverview() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <OverviewPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const emptySummary = {
  generated_at: '2026-07-26T00:00:00Z',
  window: '24h' as const,
  active_findings: 0,
  open_cases: 0,
  behavior_changes: 0,
  impacted_services: 0,
  memory_items: 0,
  severity_trend: [],
  category_breakdown: [],
};

const healthyMemory = {
  generated_at: '2026-07-26T00:00:00Z',
  enabled: true,
  status: 'healthy',
  indexed_cases: 0,
  not_indexed_cases: 0,
  stale_cases: 0,
  error_cases: 0,
  total_cases: 0,
  source: 'ops_operational_cases.memory_status',
};

describe('OverviewPage integration resilience', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders authoritative overview summary values from the backend', async () => {
    vi.mocked(api.findings).mockResolvedValue([
      {
        id: 1,
        service: 'checkout-api',
        metric_name: 'cpu_usage',
        title: 'CPU usage sustained high',
        summary: 'CPU high',
        category: 'behavior_change',
        health_status: 'critical',
        importance_score: 0.9,
        investigation_priority: 1,
        signal_ids: [],
        comparison_json: {},
        created_at: '2026-07-26T00:00:00Z',
      },
    ]);
    vi.mocked(api.cases).mockResolvedValue([]);
    vi.mocked(api.behaviorFindings).mockResolvedValue([]);
    vi.mocked(api.overviewSummary).mockResolvedValue({
      ...emptySummary,
      active_findings: 3,
      open_cases: 1,
      behavior_changes: 2,
      impacted_services: 2,
      memory_items: 1,
      severity_trend: [{ timestamp: '2026-07-26T00:00:00Z', critical: 1, high: 2, medium: 0, low: 0 }],
      category_breakdown: [{ category: 'behavior_change', count: 3 }],
    });
    vi.mocked(api.memoryStats).mockResolvedValue({ ...healthyMemory, indexed_cases: 1, total_cases: 1 });

    renderOverview();

    expect(await screen.findByText('Active Findings')).toBeInTheDocument();
    expect(screen.getAllByText('3').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Open Cases').length).toBeGreaterThan(0);
    expect(screen.getByText('Behavior Change')).toBeInTheDocument();
    expect(screen.getByText('CPU usage sustained high')).toBeInTheDocument();
  });

  it('renders empty states without fabricated trend points', async () => {
    vi.mocked(api.findings).mockResolvedValue([]);
    vi.mocked(api.cases).mockResolvedValue([]);
    vi.mocked(api.behaviorFindings).mockResolvedValue([]);
    vi.mocked(api.overviewSummary).mockResolvedValue(emptySummary);
    vi.mocked(api.memoryStats).mockResolvedValue(healthyMemory);

    renderOverview();

    expect(await screen.findByText('No severity trend points returned for this window.')).toBeInTheDocument();
    expect(screen.getByText('No finding categories returned by the findings API.')).toBeInTheDocument();
    expect(screen.getByText('No findings returned for the last 24 hours.')).toBeInTheDocument();
    expect(api.findings).toHaveBeenCalledWith(undefined, undefined, undefined, '24h');
  });

  it('shows memory unavailable when memory stats reports degraded status', async () => {
    vi.mocked(api.findings).mockResolvedValue([]);
    vi.mocked(api.cases).mockResolvedValue([]);
    vi.mocked(api.behaviorFindings).mockResolvedValue([]);
    vi.mocked(api.overviewSummary).mockResolvedValue(emptySummary);
    vi.mocked(api.memoryStats).mockResolvedValue({ ...healthyMemory, status: 'unhealthy', indexed_cases: 4 });

    renderOverview();

    expect(await screen.findAllByText('Memory unavailable')).not.toHaveLength(0);
    expect(screen.getByText('Memory unavailable.')).toBeInTheDocument();
  });

  it('keeps independent sections usable when the overview summary request fails', async () => {
    vi.mocked(api.findings).mockResolvedValue([
      {
        id: 1,
        service: 'checkout-api',
        metric_name: 'cpu_usage',
        title: 'CPU usage sustained high',
        summary: 'CPU high',
        category: 'resource',
        health_status: 'warning',
        importance_score: 0.8,
        investigation_priority: 2,
        signal_ids: [],
        comparison_json: {},
        created_at: '2026-07-26T00:00:00Z',
      },
    ]);
    vi.mocked(api.cases).mockResolvedValue([]);
    vi.mocked(api.behaviorFindings).mockResolvedValue([]);
    vi.mocked(api.overviewSummary).mockRejectedValue(new Error('malformed JSON'));
    vi.mocked(api.memoryStats).mockResolvedValue(healthyMemory);

    renderOverview();

    expect(await screen.findAllByText('Unavailable')).not.toHaveLength(0);
    expect(screen.getByText('Historical trend unavailable.')).toBeInTheDocument();
    expect(screen.getByText('Finding categories unavailable.')).toBeInTheDocument();
    expect(screen.getByText('CPU usage sustained high')).toBeInTheDocument();
  });
});
