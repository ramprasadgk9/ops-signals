import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getRecurringProblems } from './backendClient';
import { PluginCaseRecurrence } from './PluginCaseRecurrence';
import type { RecurringProblemsResponse } from '../types';

vi.mock('./backendClient', () => ({ getRecurringProblems: vi.fn() }));
const recurring = vi.mocked(getRecurringProblems);

const response: RecurringProblemsResponse = {
  available: true, window_days: 90, min_occurrences: 3, group_by: 'symptom', group_similarity: 0.8, cases_considered: 9, sampled: false,
  problems: [
    {
      name: 'Lab value drifts', named_by: 'central_case', central_case_id: 7, occurrences: 6, services: ['trend-lab'], verified_root_causes: 0, open_cases: 3,
      causes: [],
      cases: [7, 6, 5].map((id) => ({ case_id: id, title: `Case ${id}`, origin: 'detected', case_status: 'open', rca_verified: false, similarity_to_central: 1 })),
    },
  ],
};

describe('PluginCaseRecurrence', () => {
  beforeEach(() => {
    recurring.mockReset().mockResolvedValue(response);
  });

  it('says the case is one of a recurring problem, without asking the LLM for names', async () => {
    render(<PluginCaseRecurrence backendUrl="http://backend" caseId={6} />);

    expect(await screen.findByTestId('plugin-case-recurrence')).toHaveTextContent('Seen before: this problem happened 6 times in the last 90 days.');
    expect(screen.getByTestId('plugin-case-recurrence')).toHaveTextContent('No cause recorded on the other cases yet.');
    expect(recurring).toHaveBeenCalledWith('http://backend', 90, 'symptom', 3, false);
  });

  it('shows nothing for a one-off case', async () => {
    const { container } = render(<PluginCaseRecurrence backendUrl="http://backend" caseId={99} />);
    await waitFor(() => expect(recurring).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('shows nothing when the lookup fails', async () => {
    recurring.mockRejectedValue(new Error('down'));
    const { container } = render(<PluginCaseRecurrence backendUrl="http://backend" caseId={6} />);
    await waitFor(() => expect(recurring).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
