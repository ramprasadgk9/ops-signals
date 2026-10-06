import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SameFixElsewhere, SuggestedFixes } from './FixHistory';
import { api } from '../api/queries';
import type { SuggestedFixesResponse } from '../types';

vi.mock('../api/queries', () => ({
  api: { suggestedFixes: vi.fn(), runbookDraft: vi.fn(), sameFix: vi.fn() },
}));

function renderWithQuery(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

const held = { status: 'held' as const, label: 'Held for 30+ days' };
const cameBack = { status: 'came_back' as const, label: 'Came back after 12 days', came_back_case_id: 9, came_back_after_days: 12 };
const suggestions: SuggestedFixesResponse = {
  finding_id: 7,
  available: true,
  based_on_cases: 2,
  fixes: [
    {
      fix: 'Raised the database connection pool size.',
      root_cause: 'Database connection pool exhausted.',
      held: 1, came_back: 1, too_early: 0, verified: 2, label: 'Held 1 of 2 times',
      sources: [
        { case_id: 1, title: 'pool a', corrective_action: 'Raised the pool size', outcome: held },
        { case_id: 2, title: 'pool b', corrective_action: 'Raised the pool size', outcome: cameBack },
      ],
    },
  ],
};

describe('SuggestedFixes', () => {
  afterEach(() => vi.clearAllMocks());

  it('ranks past fixes by how often they held and drafts a runbook on request', async () => {
    vi.mocked(api.suggestedFixes).mockResolvedValue(suggestions);
    vi.mocked(api.runbookDraft).mockResolvedValue({ available: true, draft: '1. Check pool usage (case #1).', based_on_cases: [1, 2] });
    renderWithQuery(<SuggestedFixes findingId={7} />);

    expect(await screen.findByText('Raised the database connection pool size.')).toBeInTheDocument();
    expect(screen.getByText('Held 1 of 2 times')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '#2' })).toHaveAttribute('href', '/cases/2');
    expect(screen.getByText(/came back after 12 days/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Draft a runbook' }));
    expect(await screen.findByTestId('runbook-draft')).toHaveTextContent('1. Check pool usage (case #1).');
    expect(screen.getByTestId('runbook-draft')).toHaveTextContent('Not saved.');
  });

  it('says why there is no draft', async () => {
    vi.mocked(api.suggestedFixes).mockResolvedValue(suggestions);
    vi.mocked(api.runbookDraft).mockResolvedValue({ available: false, reason: 'AI assistance is not configured.', based_on_cases: [] });
    renderWithQuery(<SuggestedFixes findingId={7} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Draft a runbook' }));
    expect(await screen.findByText('AI assistance is not configured.')).toBeInTheDocument();
  });

  it('shows nothing when no past case recorded a fix', async () => {
    vi.mocked(api.suggestedFixes).mockResolvedValue({ ...suggestions, fixes: [] });
    const { container } = renderWithQuery(<SuggestedFixes findingId={7} />);
    await vi.waitFor(() => expect(api.suggestedFixes).toHaveBeenCalled());
    expect(container.querySelector('[data-testid="suggested-fixes"]')).toBeNull();
  });
});

describe('SameFixElsewhere', () => {
  afterEach(() => vi.clearAllMocks());

  it('lists other cases fixed the same way with how each fix held', async () => {
    vi.mocked(api.sameFix).mockResolvedValue({
      case_id: 3, available: true, outcome: cameBack,
      matches: [{ case_id: 5, title: 'payments-api latency from DB pool', service: 'payments-api', similarity_score: 0.86, corrective_action: 'Raised the pool size.', rca_verified: true, outcome: held }],
    });
    renderWithQuery(<SameFixElsewhere caseId={3} />);

    expect(await screen.findByRole('link', { name: 'payments-api latency from DB pool' })).toHaveAttribute('href', '/cases/5');
    expect(screen.getByText('Held for 30+ days')).toBeInTheDocument();
    expect(screen.getByText('Came back after 12 days')).toBeInTheDocument();
    expect(screen.getByText(/86% same cause and fix/)).toBeInTheDocument();
  });

  it('explains when the case has no fix yet', async () => {
    vi.mocked(api.sameFix).mockResolvedValue({ case_id: 3, available: false, reason: 'No cause or fix recorded for this case yet.', matches: [] });
    renderWithQuery(<SameFixElsewhere caseId={3} />);

    expect(await screen.findByText('No cause or fix recorded for this case yet.')).toBeInTheDocument();
  });
});
