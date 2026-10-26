import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { RecurringProblemsPage } from './RecurringProblemsPage';
import { api } from '../api/queries';

vi.mock('../api/queries', () => ({
  api: {
    cases: vi.fn(),
    memoryStats: vi.fn(),
    alertContext: vi.fn(),
    recurringProblems: vi.fn(() => Promise.resolve({ available: true, window_days: 90, min_occurrences: 3, group_by: 'symptom', group_similarity: 0.8, cases_considered: 0, sampled: false, problems: [] })),
    me: vi.fn(),
    monitoringCoverage: vi.fn(() => Promise.resolve({ available: true, reason: 'No past incidents imported in this window.', window_days: 365, incidents_considered: 0, counts: {}, services: [], incidents: [] })),
  },
}));

function renderPage(path = '/recurring-problems') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <RecurringProblemsPage />
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

describe('RecurringProblemsPage', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('says in one line how much memory is searchable, with the inventory folded away', async () => {
    vi.mocked(api.memoryStats).mockResolvedValue(memoryStats);
    vi.mocked(api.cases).mockResolvedValue([
      baseCase,
      { ...baseCase, id: 11, case_title: 'Disk saturation', memory_status: 'not_indexed' },
    ]);

    renderPage();

    expect(await screen.findByRole('heading', { name: 'Recurring problems' })).toBeInTheDocument();
    expect(screen.getByTestId('memory-status-line')).toHaveTextContent('1 past case searchable · 1 not indexed yet · all up to date');
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(screen.queryByText('CPU usage behavior changed')).not.toBeInTheDocument();

    fireEvent.click(within(screen.getByTestId('memory-status-line')).getByRole('button', { name: 'Indexing details' }));

    expect(await screen.findByText('CPU usage behavior changed')).toBeInTheDocument();
    expect(screen.queryByText('Disk saturation')).not.toBeInTheDocument();
    expect(api.cases).toHaveBeenCalledWith(200);
  });

  it('names what needs attention and offers Retry only then', async () => {
    vi.mocked(api.memoryStats).mockResolvedValue({ ...memoryStats, indexed_cases: 20, not_indexed_cases: 0, stale_cases: 2, error_cases: 1, total_cases: 23 });
    vi.mocked(api.cases).mockResolvedValue([baseCase]);

    renderPage();

    const line = await screen.findByTestId('memory-status-line');
    expect(line).toHaveTextContent('20 past cases searchable · 2 changed since indexing · 1 failed to index');
    expect(line).not.toHaveTextContent('all up to date');
    expect(within(line).getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('asks for imports in one line when monitoring coverage has nothing to check', async () => {
    vi.mocked(api.memoryStats).mockResolvedValue(memoryStats);
    vi.mocked(api.cases).mockResolvedValue([baseCase]);

    renderPage();

    expect(await screen.findByTestId('coverage-empty')).toHaveTextContent('Did your monitoring catch past incidents?');
    expect(screen.queryByText('Monitoring coverage')).not.toBeInTheDocument();
  });

  it('opens on the group a case page linked to', async () => {
    vi.mocked(api.memoryStats).mockResolvedValue(memoryStats);
    vi.mocked(api.cases).mockResolvedValue([baseCase]);
    vi.mocked(api.recurringProblems).mockResolvedValue({
      available: true, window_days: 90, min_occurrences: 3, group_by: 'symptom', group_similarity: 0.8, cases_considered: 3, sampled: false,
      problems: [
        {
          name: 'Checkout latency', named_by: 'central_case', central_case_id: 7, occurrences: 3, services: ['checkout'], verified_root_causes: 0, open_cases: 3, causes: [],
          cases: [7, 8, 9].map((id) => ({ case_id: id, title: `Case ${id}`, origin: 'detected', case_status: 'open', rca_verified: false, similarity_to_central: 1 })),
        },
      ],
    });

    renderPage('/recurring-problems?problem=7');

    expect(await screen.findByTestId('recurring-problem')).toHaveAttribute('data-highlighted', 'true');
  });

  it('offers to import past incidents when memory has no cases', async () => {
    vi.mocked(api.memoryStats).mockResolvedValue({ ...memoryStats, indexed_cases: 0, total_cases: 0 });
    vi.mocked(api.cases).mockResolvedValue([]);

    renderPage();

    expect(await screen.findByText(/Memory is empty/)).toBeInTheDocument();
    // Page header and the empty-memory prompt; the coverage prompt would only repeat them.
    expect(screen.getAllByRole('button', { name: /Import past incidents/ })).toHaveLength(2);
    expect(screen.queryByTestId('coverage-empty')).not.toBeInTheDocument();
  });

  it('labels imported cases with their source instead of a metric', async () => {
    vi.mocked(api.memoryStats).mockResolvedValue(memoryStats);
    vi.mocked(api.cases).mockResolvedValue([
      { ...baseCase, id: 12, finding_id: null, case_title: 'Checkout 500s after deploy', source: 'jira', source_id: 'OPS-412', memory_status: 'indexed' },
    ]);

    renderPage();
    fireEvent.click(within(await screen.findByTestId('memory-status-line')).getByRole('button', { name: 'Indexing details' }));

    expect(await screen.findByText('Imported · jira OPS-412')).toBeInTheDocument();
  });

  it('fills the alert preview from the import wizard link', async () => {
    vi.mocked(api.memoryStats).mockResolvedValue(memoryStats);
    vi.mocked(api.cases).mockResolvedValue([baseCase]);

    renderPage('/operational-memory?service=checkout&message=Checkout%20CPU%20pinned');

    expect(await screen.findByText(/Filled in from your import/)).toBeInTheDocument();
    expect(screen.getByDisplayValue('checkout')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Checkout CPU pinned')).toBeInTheDocument();
  });

  it('does not convert unavailable memory stats into zero counts', async () => {
    vi.mocked(api.memoryStats).mockResolvedValue({ ...memoryStats, status: 'unhealthy', indexed_cases: 4 });
    vi.mocked(api.cases).mockResolvedValue([]);

    renderPage();

    expect(await screen.findByText('Memory unavailable')).toBeInTheDocument();
    expect(screen.queryByTestId('memory-status-line')).not.toBeInTheDocument();
    expect(screen.queryByText(/past cases? searchable/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('checks alert context and renders history, outcomes, and similar cases', async () => {
    vi.mocked(api.memoryStats).mockResolvedValue(memoryStats);
    vi.mocked(api.cases).mockResolvedValue([]);
    vi.mocked(api.alertContext).mockResolvedValue({
      service: 'payments-service',
      metric_name: 'cpu_usage',
      history: {
        total_prior_occurrences: 3,
        confirmed: 2,
        rejected: 1,
        partially_confirmed: 0,
        inconclusive: 0,
        confirmed_rate: 0.67,
        most_common_root_cause: 'cpu_throttling',
        last_seen_at: '2026-08-22T14:03:00Z',
      },
      exact_match_outcomes: [
        {
          outcome_status: 'confirmed',
          root_cause_category: 'cpu_throttling',
          resolution_summary: 'Increased CPU limit from 500m to 1000m.',
          confirmed_analyzers: ['anomaly_zscore'],
          rejected_analyzers: [],
          case_id: 412,
          resolved_at: '2026-08-22T15:10:00Z',
          created_at: '2026-08-22T14:03:00Z',
        },
      ],
      similar_cases: [
        {
          case_id: 398,
          similarity_score: 0.86,
          title: 'CPU throttling on payments-service',
          case_status: 'resolved',
          outcome_status: 'confirmed',
          root_cause_summary: 'Sustained CPU usage anomaly correlated with rising throttled_seconds.',
          outcome_summary: 'Increased CPU limit.',
          reference: '/cases/398',
        },
      ],
      raw_activity: {
        finding_count: 2,
        behavior_count: 1,
        total_occurrences: 3,
        most_recent_at: '2026-08-22T14:03:00Z',
        recent_titles: ['CPU usage anomaly on payments-service'],
      },
      recommendation: 'likely_real',
      recommendation_basis: '2 of 3 prior occurrences on this service+metric were confirmed real.',
    });

    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: /Alert context preview/ }));

    fireEvent.change(screen.getByLabelText('Metric name'), { target: { value: 'cpu_usage' } });
    fireEvent.change(screen.getByLabelText('Service (optional)'), { target: { value: 'payments-service' } });
    fireEvent.change(screen.getByLabelText(/Alert message/), { target: { value: 'CPU usage spike' } });
    fireEvent.click(screen.getByRole('button', { name: 'Check Alert Context' }));

    expect(await screen.findByText('Likely real')).toBeInTheDocument();
    expect(api.alertContext).toHaveBeenCalledWith('cpu_usage', 'payments-service', 'CPU usage spike');
    expect(screen.getByText('2 of 3 prior occurrences on this service+metric were confirmed real.')).toBeInTheDocument();
    expect(screen.getByText('Increased CPU limit from 500m to 1000m.')).toBeInTheDocument();
    expect(screen.getByText('CPU throttling on payments-service')).toBeInTheDocument();
    expect(screen.getByText(/occurred/)).toBeInTheDocument();
    expect(screen.getByText('CPU usage anomaly on payments-service')).toBeInTheDocument();
  });

  it('prefers the AI raw-activity summary over the deterministic sentence, with an AI badge', async () => {
    vi.mocked(api.memoryStats).mockResolvedValue(memoryStats);
    vi.mocked(api.cases).mockResolvedValue([]);
    vi.mocked(api.alertContext).mockResolvedValue({
      service: 'payments-service',
      metric_name: 'cpu_usage',
      history: { total_prior_occurrences: 0, confirmed: 0, rejected: 0, partially_confirmed: 0, inconclusive: 0, confirmed_rate: null, most_common_root_cause: null, last_seen_at: null },
      exact_match_outcomes: [],
      similar_cases: [],
      raw_activity: {
        finding_count: 3,
        behavior_count: 0,
        total_occurrences: 3,
        most_recent_at: '2026-09-13T00:00:00Z',
        recent_titles: ['CPU usage anomaly on payments-service'],
        ai_summary: 'This service has repeatedly shown CPU anomalies, but none were ever confirmed or resolved.',
      },
      recommendation: 'insufficient_history',
      recommendation_basis: 'No resolved outcomes recorded for this service/metric, but it has occurred 3 time(s) before with no case ever filed - see raw activity below.',
    });

    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: /Alert context preview/ }));

    fireEvent.change(screen.getByLabelText('Metric name'), { target: { value: 'cpu_usage' } });
    fireEvent.click(screen.getByRole('button', { name: 'Check Alert Context' }));

    expect(await screen.findByText('This service has repeatedly shown CPU anomalies, but none were ever confirmed or resolved.')).toBeInTheDocument();
    expect(screen.queryByText(/This exact service\/metric occurred/)).not.toBeInTheDocument();
    expect(screen.getByText('AI')).toBeInTheDocument();
  });
});

describe('RecurringProblemsPage alert preview with only similar cases', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('says "Seen before" instead of insufficient history and shows the imported fix', async () => {
    vi.mocked(api.memoryStats).mockResolvedValue(memoryStats);
    vi.mocked(api.cases).mockResolvedValue([]);
    vi.mocked(api.alertContext).mockResolvedValue({
      service: 'checkout',
      metric_name: 'cpu_usage',
      history: { total_prior_occurrences: 0, confirmed: 0, partially_confirmed: 0, rejected: 0, inconclusive: 0, confirmed_rate: null, most_common_root_cause: null, last_seen_at: null },
      exact_match_outcomes: [],
      similar_cases: [
        {
          case_id: 25, similarity_score: 0.58, title: 'Checkout CPU pinned at 95% after release 4.2', case_status: 'resolved',
          root_cause_summary: 'Schema validation on every call', corrective_action: 'Cached the compiled schema',
          origin: 'imported', source: 'jira', source_id: 'OPS-101', reference: '/cases/25',
        },
      ],
      raw_activity: { finding_count: 0, behavior_count: 0, total_occurrences: 0, most_recent_at: null, recent_titles: [] },
      recommendation: 'insufficient_history',
      recommendation_basis: 'Seen before: 1 similar past incident imported from incident records, no real-vs-noise verdict yet.',
    } as never);

    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: /Alert context preview/ }));
    fireEvent.change(await screen.findByLabelText(/Alert message/), { target: { value: 'checkout CPU high' } });
    fireEvent.click(screen.getByRole('button', { name: 'Check Alert Context' }));

    expect(await screen.findByText('Seen before')).toBeInTheDocument();
    expect(screen.queryByText('Insufficient history')).not.toBeInTheDocument();
    expect(screen.getByText('Imported · jira OPS-101')).toBeInTheDocument();
    expect(screen.getByText('Cached the compiled schema')).toBeInTheDocument();
  });
});

describe('RecurringProblemsPage for someone who is not an Admin', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('locks Import past incidents, which only Admins may do', async () => {
    vi.mocked(api.me).mockResolvedValue({ signed_in: true, name: 'sam@example.com', role: 'Viewer', via: 'proxy', groups: [], granted_by: null, mode: 'proxy-headers', problem: null });
    vi.mocked(api.memoryStats).mockResolvedValue(memoryStats);
    vi.mocked(api.cases).mockResolvedValue([]);
    renderPage();

    const buttons = await screen.findAllByRole('button', { name: '🔒 Import past incidents' });
    for (const button of buttons) expect(button).toBeDisabled();
    expect(screen.getByText('Only Ops Signals admins can import past incidents.')).toBeInTheDocument();
  });
});
