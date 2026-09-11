import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../api/queries';
import { AppShell } from '../components/AppShell';
import { AppRoutes } from '../routes/AppRoutes';

vi.mock('../api/queries', () => ({
  api: {
    health: vi.fn().mockResolvedValue({ status: 'ok' }),
    memoryHealth: vi.fn().mockResolvedValue({ status: 'ok' }),
    findings: vi.fn().mockResolvedValue([]),
    findingsSearch: vi.fn().mockResolvedValue([]),
    cases: vi.fn().mockResolvedValue([]),
    analysisRuns: vi.fn().mockResolvedValue([]),
    behaviorFindings: vi.fn().mockResolvedValue([]),
    autonomousPolicyRuns: vi.fn().mockResolvedValue([]),
    autonomousQuestionAnswer: vi.fn(),
    autonomousScopeOptions: vi.fn().mockResolvedValue({ services: ['checkout'], namespaces: [], environments: ['production'] }),
    autonomousPreview: vi.fn(),
    autonomousRunOnce: vi.fn(),
  },
}));

function renderRoute(path = '/autonomous-monitoring') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <AppShell>
          <AppRoutes />
        </AppShell>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('AutonomousMonitoringPage', () => {
  it('renders the dedicated autonomous configure route and sidebar item', async () => {
    renderRoute();

    expect(screen.getByRole('link', { name: /Autonomous Analysis Configure/ })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Autonomous Analysis Configure' })).toBeInTheDocument();
    expect(screen.getByText('Configure Autonomous Analysis')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Preview' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run once' })).toBeInTheDocument();
  });

  it('shows an idle results dashboard before any run has completed', async () => {
    vi.mocked(api.autonomousPolicyRuns).mockResolvedValue([
      {
        policy_run_id: 'run-1',
        id: 'run-1',
        status: 'completed',
        trigger: 'run_once',
        policy_id: null,
        started_at: '2026-08-23T17:21:56Z',
        completed_at: '2026-08-23T17:22:56Z',
        metrics_discovered: 4,
        metrics_selected: 1,
        jobs_planned: 1,
        jobs_completed: 1,
        jobs_skipped: 3,
        jobs_failed: 0,
        findings_created: 1,
      },
    ]);
    vi.mocked(api.findings).mockResolvedValue([
      {
        id: 1,
        title: 'CPU usage moved',
        service: 'ruptures-lab',
        metric_name: 'cpu_usage',
        category: 'Behavior Change',
        health_status: 'warning',
        importance_score: 0.61,
        investigation_priority: 2,
        summary: 'CPU changed.',
        created_at: '2026-08-23T17:20:00Z',
        analysis_run_id: 'analysis-1',
        signal_ids: [],
        comparison_json: {},
      },
    ]);
    renderRoute();

    expect(await screen.findByText('Configure Autonomous Analysis')).toBeInTheDocument();
    expect(await screen.findByText('Autonomous Monitoring Overview')).toBeInTheDocument();
    expect(screen.getByText('No autonomous analysis has been completed yet.')).toBeInTheDocument();
    // No run has been triggered yet, so results queries stay disabled and this finding stays hidden.
    expect(screen.queryByRole('link', { name: 'cpu_usage' })).not.toBeInTheDocument();
  });

  it('renders the run results in the dashboard right after Run once completes', async () => {
    vi.mocked(api.findings).mockResolvedValue([
      {
        id: 1,
        title: 'CPU usage moved',
        service: 'ruptures-lab',
        metric_name: 'cpu_usage',
        category: 'Behavior Change',
        health_status: 'warning',
        importance_score: 0.61,
        investigation_priority: 2,
        summary: 'CPU changed.',
        created_at: '2026-08-23T17:20:00Z',
        analysis_run_id: 'analysis-1',
        signal_ids: [],
        comparison_json: {},
      },
    ]);
    vi.mocked(api.autonomousRunOnce).mockResolvedValue({
      status: 'completed',
      policy_run_id: 'run-1',
      planned_jobs: 1,
      executed_jobs: 1,
      skipped_jobs: 0,
      failed_jobs: 0,
      analysis_window: '24h',
      requested_start: '2026-08-23T17:20:00Z',
      requested_end: '2026-08-23T17:21:00Z',
      step: 'completed',
      preview: {
        scope_summary: {},
        metrics_discovered: 1,
        metrics_matched: 1,
        metrics_excluded: 0,
        planned_jobs: 1,
        budget_limited: 0,
        warnings: [],
        items: [],
      },
      results: [
        {
          metric_name: 'cpu_usage',
          service: 'ruptures-lab',
          promql: 'cpu_usage',
          status: 'completed',
          analysis_run_id: 'analysis-1',
          sample_count: 120,
          series_count: 1,
          signal_count: 1,
          findings_count: 1,
          behavior_findings_count: 0,
          warnings: [],
        },
      ],
      warnings: [],
    });
    renderRoute();

    fireEvent.click(await screen.findByRole('button', { name: 'Run once' }));

    expect(await screen.findByRole('link', { name: 'cpu_usage' })).toBeInTheDocument();
    expect(screen.queryByText('No autonomous analysis has been completed yet.')).not.toBeInTheDocument();
  });
});
