import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { OverviewPage } from './OverviewPage';
import { api } from '../api/queries';
import type { Finding, OperationalCase } from '../types';

vi.mock('../api/queries', () => ({
  api: {
    findings: vi.fn(),
    cases: vi.fn(),
    behaviorFindings: vi.fn(),
    overviewSummary: vi.fn(),
    memoryStats: vi.fn(),
    autonomousPolicyRuns: vi.fn(),
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

const autonomousRun = {
  policy_run_id: 'run-1',
  id: 'run-1',
  status: 'completed',
  trigger: 'run_once',
  policy_id: null,
  started_at: '2026-07-26T00:00:00Z',
  completed_at: '2026-07-26T00:01:00Z',
  metrics_discovered: 4,
  metrics_selected: 1,
  jobs_planned: 1,
  jobs_completed: 1,
  jobs_skipped: 3,
  jobs_failed: 0,
  findings_created: 2,
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
    vi.mocked(api.autonomousPolicyRuns).mockResolvedValue([autonomousRun]);

    renderOverview();

    expect(await screen.findByText('Active Findings')).toBeInTheDocument();
    expect(screen.getAllByText('3').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Open Cases').length).toBeGreaterThan(0);
    expect(screen.getByText('Operational Summary')).toBeInTheDocument();
    expect(screen.getByText('Needs Attention')).toBeInTheDocument();
    expect(screen.getByText('CPU usage sustained high')).toBeInTheDocument();
    expect(screen.getByText('Autonomous Analysis')).toBeInTheDocument();
    expect(screen.getByText('checkout-api / cpu_usage')).toBeInTheDocument();
    expect(screen.getByText('Findings')).toBeInTheDocument();
    expect(screen.getByText('Generated')).toBeInTheDocument();
    expect(screen.getByText('Failed Jobs')).toBeInTheDocument();
    expect(screen.getByText('Execution errors')).toBeInTheDocument();
    expect(screen.getByText('Top Metric')).toBeInTheDocument();
    expect(screen.getByText('cpu_usage')).toBeInTheDocument();
    expect(screen.queryByText('Memory Items')).not.toBeInTheDocument();
    expect(screen.queryByText('Finding Severity Trend')).not.toBeInTheDocument();
  });

  it('only labels a "Needs Attention" row with a case when that exact finding was promoted, not just any finding sharing its metric name', async () => {
    // Regression test: a prior fallback matched a case to a finding by metric_name alone,
    // ignoring service - so an un-cased finding from one service showed up mislabeled with the
    // case ID of an unrelated, differently-serviced finding that happened to share a metric name.
    const cpuFindingFromCasedService: Finding = {
      id: 36,
      service: 'ruptures-lab',
      metric_name: 'cpu_usage',
      title: 'cpu_usage is trending in one direction.',
      summary: 'trend',
      category: 'behavior_change',
      health_status: 'significant',
      importance_score: 0.7,
      investigation_priority: 2,
      signal_ids: [],
      comparison_json: {},
      created_at: '2026-09-19T15:03:09Z',
    };
    const cpuFindingFromUncasedService: Finding = {
      ...cpuFindingFromCasedService,
      id: 41,
      service: 'test-otlp-service',
      created_at: '2026-09-22T16:24:25Z',
    };
    const caseForFirstFinding: OperationalCase = {
      id: 12,
      finding_id: 36,
      analysis_run_id: 'run-36',
      case_title: 'cpu_usage is trending in one direction.',
      case_status: 'open',
      finding_snapshot: cpuFindingFromCasedService,
      investigation_status: 'not_started',
      investigation_notes: [],
      root_cause_status: 'unknown',
      root_cause_verified: false,
      outcome_status: 'pending',
      memory_status: 'not_indexed',
      created_at: '2026-09-19T15:06:49Z',
      updated_at: '2026-09-19T15:06:49Z',
    };

    vi.mocked(api.findings).mockResolvedValue([cpuFindingFromUncasedService, cpuFindingFromCasedService]);
    vi.mocked(api.cases).mockResolvedValue([caseForFirstFinding]);
    vi.mocked(api.behaviorFindings).mockResolvedValue([]);
    vi.mocked(api.overviewSummary).mockResolvedValue(emptySummary);
    vi.mocked(api.memoryStats).mockResolvedValue(healthyMemory);
    vi.mocked(api.autonomousPolicyRuns).mockResolvedValue([]);

    renderOverview();

    expect(await screen.findByText('test-otlp-service / cpu_usage')).toBeInTheDocument();
    expect(screen.getByText('ruptures-lab / cpu_usage')).toBeInTheDocument();
    // The un-cased finding must show "No case" - not the other finding's "Case #12".
    expect(screen.getByText('No case')).toBeInTheDocument();
    expect(screen.getByText('Case #12')).toBeInTheDocument();
    expect(screen.getAllByText(/Case #12/)).toHaveLength(1);
  });

  it('renders empty states without fabricated trend points', async () => {
    vi.mocked(api.findings).mockResolvedValue([]);
    vi.mocked(api.cases).mockResolvedValue([]);
    vi.mocked(api.behaviorFindings).mockResolvedValue([]);
    vi.mocked(api.overviewSummary).mockResolvedValue(emptySummary);
    vi.mocked(api.memoryStats).mockResolvedValue(healthyMemory);
    vi.mocked(api.autonomousPolicyRuns).mockResolvedValue([]);

    renderOverview();

    expect(await screen.findByText('No findings need attention in this window.')).toBeInTheDocument();
    expect(screen.getByText('No open cases returned by the API.')).toBeInTheDocument();
    expect(api.findings).toHaveBeenCalledWith(undefined, undefined, undefined, '24h');
  });

  it('keeps memory inventory off the executive overview', async () => {
    vi.mocked(api.findings).mockResolvedValue([]);
    vi.mocked(api.cases).mockResolvedValue([]);
    vi.mocked(api.behaviorFindings).mockResolvedValue([]);
    vi.mocked(api.overviewSummary).mockResolvedValue(emptySummary);
    vi.mocked(api.memoryStats).mockResolvedValue({ ...healthyMemory, status: 'unhealthy', indexed_cases: 4 });
    vi.mocked(api.autonomousPolicyRuns).mockResolvedValue([]);

    renderOverview();

    expect(await screen.findByText('Operational Summary')).toBeInTheDocument();
    expect(screen.queryByText('Memory Items')).not.toBeInTheDocument();
    expect(screen.queryByText('Memory unavailable')).not.toBeInTheDocument();
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
    vi.mocked(api.autonomousPolicyRuns).mockResolvedValue([]);

    renderOverview();

    expect(await screen.findAllByText('Unavailable')).not.toHaveLength(0);
    expect(screen.getByText(/Findings unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/Service impact unavailable/)).toBeInTheDocument();
    expect(screen.getByText('CPU usage sustained high')).toBeInTheDocument();
  });
});
