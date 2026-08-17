import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { AppShell } from '../components/AppShell';
import { AppRoutes } from '../routes/AppRoutes';

vi.mock('../api/queries', () => ({
  api: {
    health: vi.fn().mockResolvedValue({ status: 'ok' }),
    memoryHealth: vi.fn().mockResolvedValue({ status: 'ok' }),
    findings: vi.fn().mockResolvedValue([]),
    cases: vi.fn().mockResolvedValue([]),
    analysisRuns: vi.fn().mockResolvedValue([]),
    behaviorFindings: vi.fn().mockResolvedValue([]),
    autonomousPolicyRuns: vi.fn().mockResolvedValue([]),
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
  it('renders the dedicated autonomous route and sidebar item', async () => {
    renderRoute();

    expect(screen.getByRole('link', { name: /Autonomous Monitoring/ })).toBeInTheDocument();
    expect(await screen.findByText('Autonomous Monitoring Overview')).toBeInTheDocument();
    expect(screen.getByText('No autonomous analysis has been completed yet.')).toBeInTheDocument();
  });
});
