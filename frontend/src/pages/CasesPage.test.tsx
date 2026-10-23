import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
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

const IN_PROGRESS = {
  ...CASE,
  id: 7,
  case_title: 'ops_signal_lab_value shows predictable recurring behaviour.',
  investigation_status: 'in_progress',
  root_cause_summary: 'Seasonal pattern, not an incident.',
  investigation_notes: [{ timestamp: '2026-09-12T23:07:23Z', note: 'Checked last week, same shape.' }],
  finding_snapshot: { service: 'ruptures-lab', metric_name: 'ops_signal_lab_value', summary: 'Projected to drop 52%.' },
};

const RESOLVED = {
  ...CASE,
  id: 38,
  case_title: 'process_cpu_seconds_total got stuck at a constant value.',
  case_status: 'resolved',
  investigation_status: 'completed',
  root_cause_verified: false,
  resolved_at: '2026-10-16T20:40:40Z',
};

let cases: unknown[] = [CASE];

// Only what this page and its ticket card read; everything else resolves empty.
const handlers: Record<string, unknown> = {
  cases: () => Promise.resolve(cases),
  getCase: () => Promise.resolve(CASE),
  getCaseTicket: () => Promise.resolve(null),
  ticketingStatus: () => Promise.resolve({ enabled: false, provider: 'jira', provider_configured: false, webhook_secret_configured: false }),
};
vi.mock('../api/queries', () => ({
  api: new Proxy({}, { get: (_target, name: string) => handlers[name] ?? vi.fn().mockResolvedValue([]) }),
}));

function renderPage(path = '/cases') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <CasesPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('CasesPage Jira banner', () => {
  it('tells people at the top of the page that Jira ticketing exists while it is off', async () => {
    cases = [CASE];
    renderPage();

    const banner = await screen.findByTestId('jira-ticketing-hint');
    expect(banner).toHaveTextContent('Track cases in Jira');
    // Above the case list, not tucked into the side panel.
    const table = await screen.findByRole('complementary', { name: 'Case C-34' });
    expect(banner.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getAllByTestId('jira-ticketing-hint')).toHaveLength(1);
  });
});

describe('CasesPage status tabs', () => {
  it('opens on the Open tab with counts for every tab, and hides resolved cases there', async () => {
    cases = [CASE, IN_PROGRESS, RESOLVED];
    renderPage();

    expect(await screen.findByRole('tab', { name: 'Open 2' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'In progress 1' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'On hold 0' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Resolved 1' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'All 3' })).toBeInTheDocument();
    const table = screen.getByRole('table');
    expect(within(table).getByText(CASE.case_title)).toBeInTheDocument();
    expect(within(table).queryByText(RESOLVED.case_title)).not.toBeInTheDocument();
    // No owner column: assignment is not supported.
    expect(screen.queryByText('Assignment not supported')).not.toBeInTheDocument();
  });

  it('opens the tab named in the URL, as the old Investigations link does', async () => {
    cases = [CASE, IN_PROGRESS, RESOLVED];
    renderPage('/cases?tab=in-progress');

    expect(await screen.findByRole('tab', { name: 'In progress 1' })).toHaveAttribute('aria-selected', 'true');
    const table = screen.getByRole('table');
    expect(within(table).getByText(IN_PROGRESS.case_title)).toBeInTheDocument();
    expect(within(table).queryByText(CASE.case_title)).not.toBeInTheDocument();
  });

  it('shows the clicked case in the side panel, with its timeline', async () => {
    cases = [CASE, IN_PROGRESS, RESOLVED];
    renderPage();

    fireEvent.click(await screen.findByText('C-7'));
    const panel = await screen.findByRole('complementary', { name: 'Case C-7' });
    expect(within(panel).getByText('ruptures-lab')).toBeInTheDocument();
    expect(within(panel).getByText('Seasonal pattern, not an incident.')).toBeInTheDocument();
    expect(within(panel).getByText('Case created from finding')).toBeInTheDocument();
    expect(within(panel).getByText('Checked last week, same shape.')).toBeInTheDocument();
  });

  it('marks a resolved case whose root cause was not verified', async () => {
    cases = [CASE, IN_PROGRESS, RESOLVED];
    renderPage('/cases?tab=resolved');

    const panel = await screen.findByRole('complementary', { name: 'Case C-38' });
    expect(within(panel).getByText('Resolved, root cause not verified')).toBeInTheDocument();
    expect(screen.getAllByText('Root cause unconfirmed').length).toBeGreaterThan(0);
  });
});
