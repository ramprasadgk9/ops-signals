import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAiStatus, getCaseFixCameBack, getFixCameBackWhy, getRecurringProblems } from './backendClient';
import { PluginCaseRecurrence } from './PluginCaseRecurrence';
import type { RecurringProblemsResponse } from '../types';

vi.mock('./backendClient', () => ({ getRecurringProblems: vi.fn(), getCaseFixCameBack: vi.fn(), getAiStatus: vi.fn(), getFixCameBackWhy: vi.fn() }));
const recurring = vi.mocked(getRecurringProblems);
const fixCameBack = vi.mocked(getCaseFixCameBack);

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
    fixCameBack.mockReset().mockResolvedValue({ case_id: 6, available: true });
    vi.mocked(getAiStatus).mockReset().mockResolvedValue({ enabled: true, provider: 'ollama', model: 'm', endpoint: null, api_key_set: null, active: true, issue: null });
    vi.mocked(getFixCameBackWhy).mockReset();
  });

  it('shows the came-back banner instead, with the pattern count and the AI reasons on request', async () => {
    fixCameBack.mockResolvedValue({
      case_id: 6, available: true,
      came_back: { case_id: 5, title: 'Checkout slow after deploy', fixed_at: '2026-10-24T15:10:00', days: 3, fix: 'Rolled back to v2.2.', still_open: 'fix the retry loop.' },
    });
    vi.mocked(getFixCameBackWhy).mockResolvedValue({ available: true, reasons: ['The rollback may have left the retry loop in place.'] });
    render(<PluginCaseRecurrence backendUrl="http://backend" caseId={6} />);

    const banner = await screen.findByTestId('plugin-fix-came-back');
    expect(banner).toHaveTextContent('This came back 3 days after case #5 was fixed.');
    expect(banner).toHaveTextContent('Fix then: Rolled back to v2.2.');
    expect(banner).toHaveTextContent('Still open on that case: fix the retry loop.');
    await waitFor(() => expect(banner).toHaveTextContent('Seen 6 times in the last 90 days'));
    expect(screen.queryByTestId('plugin-case-recurrence')).not.toBeInTheDocument();

    fireEvent.click(await screen.findByRole('button', { name: '✦ Why might it not have held?' }));
    expect(await screen.findByTestId('plugin-fix-came-back-why')).toHaveTextContent('The rollback may have left the retry loop in place.');
    expect(getFixCameBackWhy).toHaveBeenCalledWith('http://backend', 'cases', 6);
  });

  it('tells the old case its fix did not hold', async () => {
    fixCameBack.mockResolvedValue({ case_id: 5, available: true, fix_outcome: { status: 'came_back', label: 'Came back after 3 days', came_back_case_id: 6, came_back_after_days: 3 } });
    render(<PluginCaseRecurrence backendUrl="http://backend" caseId={5} />);

    expect(await screen.findByTestId('plugin-fix-did-not-hold')).toHaveTextContent("This fix didn't hold: the problem came back 3 days later in case #6.");
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
