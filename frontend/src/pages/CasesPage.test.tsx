import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { CasesPage } from './CasesPage';

const CASE = {
  id: 34,
  finding_id: 3021,
  analysis_run_id: 'run-1',
  case_title: 'cpu_usage stopped reporting data during the selected time window.',
  case_status: 'open',
  investigation_status: 'not_started',
  root_cause_status: 'unknown',
  outcome_status: 'pending',
  memory_status: 'not_indexed',
  source: 'detected',
  finding_snapshot: { service: 'spike-lab', metric_name: 'cpu_usage', summary: 'No data for 19 minutes.' },
  investigation_notes: [],
  created_at: '2026-10-06T21:37:57Z',
  updated_at: '2026-10-06T21:37:57Z',
};

// Only what this page and its ticket card read; everything else resolves empty.
const handlers: Record<string, unknown> = {
  cases: () => Promise.resolve([CASE]),
  getCase: () => Promise.resolve(CASE),
  getCaseTicket: () => Promise.resolve(null),
  ticketingStatus: () => Promise.resolve({ enabled: false, provider: 'jira', provider_configured: false, webhook_secret_configured: false }),
};
vi.mock('../api/queries', () => ({
  api: new Proxy({}, { get: (_target, name: string) => handlers[name] ?? vi.fn().mockResolvedValue([]) }),
}));

describe('CasesPage case overview', () => {
  it('tells people Jira ticketing exists while it is off', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CasesPage />
        </MemoryRouter>
      </QueryClientProvider>
    );

    expect(await screen.findByText('Case Overview (C-34)')).toBeInTheDocument();
    expect(await screen.findByText('Track this case in Jira')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Watch how \(1 min\)/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'How to turn it on' })).toBeInTheDocument();
  });
});
