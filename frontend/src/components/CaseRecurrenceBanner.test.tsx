import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { CaseRecurrenceBanner } from './CaseRecurrenceBanner';
import { api } from '../api/queries';
import type { RecurringProblemsResponse } from '../types';

vi.mock('../api/queries', () => ({ api: { recurringProblems: vi.fn() } }));

function renderBanner(caseId: number) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><CaseRecurrenceBanner caseId={caseId} /></MemoryRouter>
    </QueryClientProvider>
  );
}

const response: RecurringProblemsResponse = {
  available: true, window_days: 90, min_occurrences: 3, group_by: 'symptom', group_similarity: 0.8, cases_considered: 9, sampled: false,
  problems: [
    {
      name: 'Lab value drifts', named_by: 'central_case', central_case_id: 7, occurrences: 6, services: ['trend-lab'], verified_root_causes: 1, open_cases: 4,
      causes: [{ case_id: 5, root_cause: 'Wrong image version', fix: 'Version changed', verified: true }],
      cases: [7, 6, 5].map((id) => ({ case_id: id, title: `Case ${id}`, origin: 'detected', case_status: 'open', rca_verified: false, similarity_to_central: 1 })),
    },
  ],
};

describe('CaseRecurrenceBanner', () => {
  afterEach(() => vi.mocked(api.recurringProblems).mockReset());

  it('says how often the problem happened, what was found before, and links to the pattern', async () => {
    vi.mocked(api.recurringProblems).mockResolvedValue(response);
    renderBanner(6);

    const banner = await screen.findByTestId('case-recurrence');
    expect(banner).toHaveTextContent('Seen before: this problem happened 6 times in the last 90 days.');
    expect(banner).toHaveTextContent('Found and verified on case #5: Wrong image version — fixed by: Version changed');
    expect(screen.getByRole('link', { name: 'See the pattern →' })).toHaveAttribute('href', '/recurring-problems?problem=7');
    // Only which group the case is in is needed: no LLM naming.
    expect(api.recurringProblems).toHaveBeenCalledWith(90, 3, 'symptom', false);
  });

  it('shows nothing for a case that is not part of a recurring problem', async () => {
    vi.mocked(api.recurringProblems).mockResolvedValue(response);
    const { container } = renderBanner(99);

    await vi.waitFor(() => expect(api.recurringProblems).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
