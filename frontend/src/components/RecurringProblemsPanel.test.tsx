import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { RecurringProblemsPanel } from './RecurringProblemsPanel';
import { NoveltyBadge } from './NoveltyBadge';
import { api } from '../api/queries';
import type { RecurringProblemsResponse } from '../types';

vi.mock('../api/queries', () => ({
  api: {
    recurringProblems: vi.fn(),
  },
}));

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  );
}

const response = (overrides: Partial<RecurringProblemsResponse> = {}): RecurringProblemsResponse => ({
  available: true,
  window_days: 90,
  min_occurrences: 3,
  group_by: 'symptom',
  group_similarity: 0.8,
  cases_considered: 9,
  sampled: false,
  problems: [
    {
      name: 'Checkout latency from DB pool exhaustion',
      named_by: 'ai',
      central_case_id: 3,
      occurrences: 3,
      services: ['checkout-api'],
      first_seen: '2026-08-01T00:00:00Z',
      last_seen: '2026-10-01T00:00:00Z',
      verified_root_causes: 2,
      open_cases: 1,
      causes: [{ case_id: 3, root_cause: 'Connection pool exhausted', fix: 'Raised pool size', verified: true }],
      cases: [
        { case_id: 3, title: 'checkout-api pool exhausted again', service: 'checkout-api', created_at: '2026-10-01T00:00:00Z', origin: 'detected', case_status: 'resolved', rca_verified: true, similarity_to_central: 1 },
        { case_id: 2, title: 'checkout-api pool saturated', service: 'checkout-api', created_at: '2026-09-01T00:00:00Z', origin: 'detected', case_status: 'resolved', rca_verified: true, similarity_to_central: 0.9 },
        { case_id: 1, title: 'Checkout slow after release', service: 'checkout-api', created_at: '2026-08-01T00:00:00Z', origin: 'imported', case_status: 'open', rca_verified: false, similarity_to_central: 0.82 },
      ],
    },
  ],
  ...overrides,
});

describe('RecurringProblemsPanel', () => {
  afterEach(() => vi.mocked(api.recurringProblems).mockReset());

  it('shows each recurring problem with how often it happened and its causes', async () => {
    vi.mocked(api.recurringProblems).mockResolvedValue(response());
    renderWithProviders(<RecurringProblemsPanel />);

    expect(await screen.findByText('Checkout latency from DB pool exhaustion')).toBeInTheDocument();
    expect(screen.getByText('3 times in 90 days')).toBeInTheDocument();
    expect(screen.getByText('AI-named')).toBeInTheDocument();
    expect(screen.getByText(/Raised pool size/)).toHaveTextContent('Cause (verified): Connection pool exhausted — Fix: Raised pool size');
    expect(screen.getByTestId('recurring-next-step')).toHaveTextContent('Worth a lasting fix. Same verified cause each time it was checked: Connection pool exhausted');
    expect(screen.queryByText('checkout-api pool saturated')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Show 3 cases' }));
    expect(screen.getByRole('link', { name: 'checkout-api pool saturated' })).toHaveAttribute('href', '/cases/2');
  });

  it('draws each occurrence on a timeline, coloured by state, with a legend and links', async () => {
    vi.mocked(api.recurringProblems).mockResolvedValue(response());
    renderWithProviders(<RecurringProblemsPanel />);

    const timeline = await screen.findByTestId('occurrence-timeline');
    const dots = within(timeline).getAllByRole('listitem');
    expect(dots).toHaveLength(3);
    expect(dots.map((dot) => dot.getAttribute('href')).sort()).toEqual(['/cases/1', '/cases/2', '/cases/3']);
    expect(dots.find((dot) => dot.getAttribute('href') === '/cases/1')).toHaveAccessibleName(/Still open/);
    const legend = screen.getByTestId('occurrence-legend');
    expect(within(legend).getByText('Still open')).toBeInTheDocument();
    expect(within(legend).getByText('Fixed, cause verified')).toBeInTheDocument();
    expect(within(legend).queryByText('Fixed, cause not verified')).not.toBeInTheDocument();
  });

  const problems = (count: number) => {
    const [first] = response().problems;
    return Array.from({ length: count }, (_, index) =>
      index === 1 ? { ...first, name: 'Disk filling on inventory', central_case_id: 9, occurrences: 4 } : { ...first, name: `Problem ${index}`, central_case_id: 20 + index },
    );
  };

  it('ranks problems against each other as a jump list once there are four or more', async () => {
    vi.mocked(api.recurringProblems).mockResolvedValue(response({ problems: problems(4) }));
    renderWithProviders(<RecurringProblemsPanel />);

    const ranking = await screen.findByTestId('problem-ranking');
    expect(within(ranking).getByRole('button', { name: /Disk filling on inventory/ })).toHaveTextContent('4');
    expect(within(ranking).getAllByRole('button')).toHaveLength(4);
  });

  it('shows no ranking for fewer than four problems: each card shows its count', async () => {
    vi.mocked(api.recurringProblems).mockResolvedValue(response({ problems: problems(3) }));
    renderWithProviders(<RecurringProblemsPanel />);

    expect(await screen.findAllByTestId('recurring-problem')).toHaveLength(3);
    expect(screen.queryByTestId('problem-ranking')).not.toBeInTheDocument();
  });

  it('links a problem with no cause to its latest open case, to record one', async () => {
    const problem = response().problems[0];
    vi.mocked(api.recurringProblems).mockResolvedValue(response({ problems: [{ ...problem, causes: [], verified_root_causes: 0 }] }));
    renderWithProviders(<RecurringProblemsPanel />);

    const step = await screen.findByTestId('recurring-next-step');
    expect(step).toHaveTextContent('No cause recorded yet.');
    expect(within(step).getByRole('link', { name: 'Add a cause' })).toHaveAttribute('href', '/cases/1');
  });

  it('says which window the compared cases came from', async () => {
    vi.mocked(api.recurringProblems).mockResolvedValue(response({ cases_considered: 21 }));
    renderWithProviders(<RecurringProblemsPanel />);

    expect(await screen.findByText(/21 cases from the last 90 days compared/)).toBeInTheDocument();
  });

  it('keeps causes beyond the first two one click away', async () => {
    const problem = response().problems[0];
    const causes = Array.from({ length: 3 }, (_, index) => ({
      case_id: 100 + index,
      root_cause: index === 2 ? 'Payment provider slow' : `Pool exhausted ${index}`,
      fix: null,
      verified: index < 2,
    }));
    vi.mocked(api.recurringProblems).mockResolvedValue(response({ problems: [{ ...problem, causes }] }));
    renderWithProviders(<RecurringProblemsPanel />);

    await screen.findByText(/Pool exhausted 0/);
    expect(screen.queryByText(/Payment provider slow/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Show 1 more cause' }));
    expect(screen.getByText(/Payment provider slow/)).toBeInTheDocument();
  });

  it('asks for the chosen window', async () => {
    vi.mocked(api.recurringProblems).mockResolvedValue(response({ problems: [] }));
    renderWithProviders(<RecurringProblemsPanel />);

    await screen.findByText(/No problem happened 3 or more times/);
    fireEvent.click(screen.getByText('180 days'));
    await waitFor(() => expect(api.recurringProblems).toHaveBeenLastCalledWith(180, 3, 'symptom'));
    fireEvent.click(screen.getByText('By cause'));
    await waitFor(() => expect(api.recurringProblems).toHaveBeenLastCalledWith(180, 3, 'cause'));
  });

  it('explains when memory is not available', async () => {
    vi.mocked(api.recurringProblems).mockResolvedValue(response({ available: false, reason: 'Operational memory is not enabled.', problems: [] }));
    renderWithProviders(<RecurringProblemsPanel />);

    expect(await screen.findByText('Operational memory is not enabled.')).toBeInTheDocument();
  });
});

describe('NoveltyBadge', () => {
  it('shows the label and the reason', () => {
    render(<NoveltyBadge novelty={{ level: 'new', label: 'New pattern', explanation: 'Nothing in memory looks like this.', matching_cases: 0, all_matching_cases: 0 }} />);

    expect(screen.getByText('New pattern')).toBeInTheDocument();
    expect(screen.getByText('Nothing in memory looks like this.')).toBeInTheDocument();
  });

  it('renders nothing without novelty', () => {
    const { container } = render(<NoveltyBadge novelty={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
