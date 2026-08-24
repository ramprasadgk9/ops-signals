import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
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

  it('keeps autonomous details out of the configure-only page', async () => {
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
    expect(screen.queryByText('Autonomous Monitoring Overview')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'cpu_usage' })).not.toBeInTheDocument();
  });
});
