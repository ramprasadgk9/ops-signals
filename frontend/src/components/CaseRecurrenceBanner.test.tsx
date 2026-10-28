import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { CaseRecurrenceBanner } from './CaseRecurrenceBanner';
import { api } from '../api/queries';
import type { RecurringProblemsResponse } from '../types';

vi.mock('../api/queries', () => ({ api: { recurringProblems: vi.fn(), caseFixCameBack: vi.fn(), caseFixCameBackWhy: vi.fn(), aiStatus: vi.fn() } }));

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
  beforeEach(() => {
    vi.mocked(api.caseFixCameBack).mockResolvedValue({ case_id: 6, available: true });
    vi.mocked(api.aiStatus).mockResolvedValue({ enabled: true, provider: 'ollama', model: 'm', endpoint: null, api_key_set: null, active: true, issue: null });
  });
  afterEach(() => vi.mocked(api.recurringProblems).mockReset());

  it('shows the came-back banner instead when the case is back soon after a fix, with the pattern folded in', async () => {
    vi.mocked(api.recurringProblems).mockResolvedValue(response);
    vi.mocked(api.caseFixCameBack).mockResolvedValue({
      case_id: 6, available: true,
      came_back: { case_id: 5, title: 'Checkout slow', fixed_at: '2026-10-24T15:10:00', days: 3, fix: 'Rolled back to v2.2.', still_open: 'fix the retry loop.' },
    });
    vi.mocked(api.caseFixCameBackWhy).mockResolvedValue({ available: false, reasons: [], reason_code: 'not_enough' });
    renderBanner(6);

    const banner = await screen.findByTestId('fix-came-back');
    expect(banner).toHaveTextContent('This came back 3 days after case #5 was fixed.');
    expect(banner).toHaveTextContent('Still open on that case: fix the retry loop.');
    await vi.waitFor(() => expect(banner).toHaveTextContent('Seen 6 times in the last 90 days.'));
    expect(screen.getByRole('link', { name: 'Open case #5 →' })).toHaveAttribute('href', '/cases/5');
    expect(screen.getByRole('link', { name: 'See the pattern →' })).toHaveAttribute('href', '/recurring-problems?problem=7');
    expect(screen.queryByTestId('case-recurrence')).not.toBeInTheDocument();

    fireEvent.click(await screen.findByRole('button', { name: 'Why might it not have held?' }));
    expect(await screen.findByTestId('fix-came-back-why')).toHaveTextContent('Not enough in the cases to say why.');
    expect(api.caseFixCameBackWhy).toHaveBeenCalledWith(6);
  });

  it('tells the old case its fix did not hold', async () => {
    vi.mocked(api.recurringProblems).mockResolvedValue({ ...response, problems: [] });
    vi.mocked(api.caseFixCameBack).mockResolvedValue({ case_id: 5, available: true, fix_outcome: { status: 'came_back', label: 'Came back after 3 days', came_back_case_id: 6, came_back_after_days: 3 } });
    renderBanner(5);

    expect(await screen.findByTestId('fix-did-not-hold')).toHaveTextContent("This fix didn't hold: the problem came back 3 days later in case #6.");
    expect(screen.getByRole('link', { name: 'Open case #6 →' })).toHaveAttribute('href', '/cases/6');
  });

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
