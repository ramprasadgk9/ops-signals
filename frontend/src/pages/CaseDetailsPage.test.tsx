import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { CaseDetailsPage } from './CaseDetailsPage';
import { ApiError } from '../api/client';
import { api } from '../api/queries';
import type { OperationalCase } from '../types';

vi.mock('../api/queries', () => ({
  api: {
    getCase: vi.fn(),
    signals: vi.fn().mockResolvedValue([]),
    getSimilarCases: vi.fn().mockResolvedValue({ source_case_id: 1, matches: [] }),
    indexCaseMemory: vi.fn(),
    updateInvestigation: vi.fn(),
    updateRCA: vi.fn(),
    updateResolution: vi.fn(),
    caseStillSeen: vi.fn().mockResolvedValue({ still_seen: false, finding_id: null, seen_at: null }),
    aiStatus: vi.fn().mockResolvedValue({ enabled: false, provider: 'noop', model: null, endpoint: null, api_key_set: null, active: false, issue: null }),
    suggestRca: vi.fn(),
    suggestResolution: vi.fn(),
    caseTimeline: vi.fn().mockResolvedValue({ events: [], time_to_fix_minutes: null, memory_text: 'Operational Case' }),
    updateWriteup: vi.fn(),
    suggestWriteup: vi.fn(),
    investigations: vi.fn().mockResolvedValue([]),
    getInvestigation: vi.fn(),
    investigationNoteDraft: vi.fn(),
  },
}));

function baseCase(overrides: Partial<OperationalCase> = {}): OperationalCase {
  return {
    id: 1,
    finding_id: 10,
    analysis_run_id: 'run-1',
    case_title: 'CPU usage anomaly on payments-service',
    case_status: 'open',
    finding_snapshot: {
      service: 'payments-service',
      metric_name: 'cpu_usage',
      title: 'CPU usage anomaly',
      summary: 'CPU moved outside its normal range.',
      category: 'behavior_change',
      health_status: 'critical',
      importance_score: 0.9,
      investigation_priority: 0.9,
      signal_ids: [],
      comparison_json: {},
    },
    investigation_status: 'not_started',
    investigation_notes: [],
    root_cause_status: 'unknown',
    root_cause_verified: false,
    outcome_status: 'pending',
    memory_status: 'not_indexed',
    created_at: '2026-09-14T00:00:00Z',
    updated_at: '2026-09-14T00:00:00Z',
    ...overrides,
  };
}

function GoTo({ to }: { to: string }) {
  const navigate = useNavigate();
  return <button onClick={() => navigate(to)}>Go to {to}</button>;
}

function renderPage(path = '/cases/1') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/cases/:caseId" element={<><CaseDetailsPage /><GoTo to="/cases/1?tab=root-cause" /></>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

async function openResolutionPanel() {
  const tab = await screen.findByRole('tab', { name: /Resolution/i });
  fireEvent.click(tab);
  return screen.getByRole('tabpanel');
}

async function pickResolvedOutcome(panel: HTMLElement) {
  const comboboxes = within(panel).getAllByRole('combobox');
  fireEvent.mouseDown(comboboxes[0]);
  fireEvent.click(await screen.findByRole('option', { name: 'Resolved' }));
}

async function pickLearningOutcome(panel: HTMLElement, optionNamePattern: RegExp) {
  const comboboxes = within(panel).getAllByRole('combobox');
  fireEvent.mouseDown(comboboxes[1]);
  fireEvent.click(await screen.findByRole('option', { name: optionNamePattern }));
}

describe('CaseDetailsPage resolution tab', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('opens on the tab a link names', async () => {
    vi.mocked(api.getCase).mockResolvedValue(baseCase());

    renderPage('/cases/1?tab=root-cause');

    expect(await screen.findByRole('tab', { name: 'Root Cause' })).toHaveAttribute('aria-selected', 'true');
  });

  it('links back to the finding the case came from', async () => {
    vi.mocked(api.getCase).mockResolvedValue(baseCase());

    renderPage();

    const from = await screen.findByTestId('case-finding-link');
    expect(within(from).getByRole('link', { name: 'finding #10' })).toHaveAttribute('href', '/findings?finding=10');
  });

  it('switches to the tab a link names when the case is already open', async () => {
    vi.mocked(api.getCase).mockResolvedValue(baseCase());

    renderPage('/cases/1?tab=similar-cases');
    expect(await screen.findByRole('tab', { name: 'Similar Cases' })).toHaveAttribute('aria-selected', 'true');

    // Demo mode's "Create the case" reuses this case and links to its Root Cause tab.
    fireEvent.click(screen.getByRole('button', { name: 'Go to /cases/1?tab=root-cause' }));
    expect(await screen.findByRole('tab', { name: 'Root Cause' })).toHaveAttribute('aria-selected', 'true');

    // Again after picking another tab: the same link still goes to Root Cause.
    fireEvent.click(screen.getByRole('tab', { name: 'Evidence' }));
    fireEvent.click(screen.getByRole('button', { name: 'Go to /cases/1?tab=root-cause' }));
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Root Cause' })).toHaveAttribute('aria-selected', 'true'));
  });

  it('hides the Learning Outcome field when Outcome Status is not Resolved', async () => {
    vi.mocked(api.getCase).mockResolvedValue(baseCase());

    renderPage();
    const panel = await openResolutionPanel();

    expect(within(panel).getAllByRole('combobox')).toHaveLength(1);
  });

  it('requires a Learning Outcome before Save Resolution is enabled, once Resolved is picked', async () => {
    vi.mocked(api.getCase).mockResolvedValue(baseCase());

    renderPage();
    const panel = await openResolutionPanel();
    await pickResolvedOutcome(panel);

    expect(within(panel).getAllByRole('combobox')).toHaveLength(2);
    expect(screen.getByRole('button', { name: /Save Resolution/i })).toBeDisabled();

    await pickLearningOutcome(panel, /Confirmed — this was a real issue/i);

    expect(screen.getByRole('button', { name: /Save Resolution/i })).not.toBeDisabled();
  });

  it('warns when Resolved is picked while the problem is still being found, and still saves', async () => {
    vi.mocked(api.getCase).mockResolvedValue(baseCase());
    vi.mocked(api.caseStillSeen).mockResolvedValueOnce({ still_seen: true, finding_id: 57, seen_at: '2026-09-14T10:30:00Z' });
    vi.mocked(api.updateResolution).mockResolvedValue(baseCase({ outcome_status: 'resolved' }));

    renderPage();
    const panel = await openResolutionPanel();
    expect(screen.queryByTestId('still-seen-warning')).toBeNull();
    await pickResolvedOutcome(panel);

    const warning = await screen.findByTestId('still-seen-warning');
    expect(warning).toHaveTextContent('This problem is still showing up.');
    expect(within(warning).getByRole('link', { name: 'finding #57' })).toHaveAttribute('href', '/findings?finding=57');
    await pickLearningOutcome(panel, /Confirmed — this was a real issue/i);
    fireEvent.click(screen.getByRole('button', { name: /Save Resolution/i }));

    await vi.waitFor(() => expect(api.updateResolution).toHaveBeenCalled());
  });

  it('shows no warning when the problem is not being found any more', async () => {
    vi.mocked(api.getCase).mockResolvedValue(baseCase());

    renderPage();
    const panel = await openResolutionPanel();
    await pickResolvedOutcome(panel);

    await waitFor(() => expect(api.caseStillSeen).toHaveBeenCalledWith(1));
    expect(screen.queryByTestId('still-seen-warning')).toBeNull();
  });

  it('does not check while the case is already resolved', async () => {
    vi.mocked(api.caseStillSeen).mockClear();
    vi.mocked(api.getCase).mockResolvedValue(baseCase({ outcome_status: 'resolved', case_status: 'resolved' }));

    renderPage();
    await openResolutionPanel();

    expect(api.caseStillSeen).not.toHaveBeenCalled();
  });

  it('sends learning_outcome_status when saving a resolved case', async () => {
    vi.mocked(api.getCase).mockResolvedValue(baseCase());
    vi.mocked(api.updateResolution).mockResolvedValue(baseCase({ outcome_status: 'resolved' }));

    renderPage();
    const panel = await openResolutionPanel();
    await pickResolvedOutcome(panel);
    await pickLearningOutcome(panel, /Rejected/i);

    fireEvent.click(screen.getByRole('button', { name: /Save Resolution/i }));

    await vi.waitFor(() => {
      expect(api.updateResolution).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ outcome_status: 'resolved', learning_outcome_status: 'rejected' })
      );
    });
  });

  it('shows a visible error instead of failing silently when the save is rejected', async () => {
    vi.mocked(api.getCase).mockResolvedValue(baseCase());
    vi.mocked(api.updateResolution).mockRejectedValue(
      new Error('learning_outcome_status is required when resolving or closing a case')
    );

    renderPage();
    const panel = await openResolutionPanel();
    await pickResolvedOutcome(panel);
    await pickLearningOutcome(panel, /Inconclusive/i);

    fireEvent.click(screen.getByRole('button', { name: /Save Resolution/i }));

    expect(await screen.findByText('learning_outcome_status is required when resolving or closing a case')).toBeInTheDocument();
  });
});

describe('CaseDetailsPage for an imported case', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  const importedCase = () =>
    baseCase({
      finding_id: null,
      analysis_run_id: 'import:batch1',
      case_status: 'resolved',
      outcome_status: 'resolved',
      root_cause_status: 'confirmed',
      root_cause_summary: 'Connection pool exhausted',
      source: 'jira',
      source_id: 'OPS-412',
      source_url: 'https://jira.example.com/browse/OPS-412',
      finding_snapshot: {
        source_type: 'imported',
        service: 'checkout-api',
        metric_name: null,
        title: 'Checkout 500s after deploy',
        summary: 'Checkout returned 500 for 12% of requests.',
        category: 'imported_incident',
        health_status: 'High',
        importance_score: 0,
      } as unknown as OperationalCase['finding_snapshot'],
    });

  it('shows where the case was imported from and does not load signals', async () => {
    vi.mocked(api.getCase).mockResolvedValue(importedCase());

    renderPage();

    const origin = await screen.findByTestId('imported-case-origin');
    expect(within(origin).getByText('Imported · jira OPS-412')).toBeInTheDocument();
    expect(within(origin).getByRole('link')).toHaveAttribute('href', 'https://jira.example.com/browse/OPS-412');
    expect(api.signals).not.toHaveBeenCalled();
    expect(screen.queryByTestId('case-finding-link')).not.toBeInTheDocument();
  });

  it('saves a resolution without asking for a learning outcome', async () => {
    vi.mocked(api.getCase).mockResolvedValue(importedCase());
    vi.mocked(api.updateResolution).mockResolvedValue(importedCase());

    renderPage();
    const panel = await openResolutionPanel();
    await pickResolvedOutcome(panel);

    expect(within(panel).getAllByRole('combobox')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: /Save Resolution/i }));

    await vi.waitFor(() => {
      expect(api.updateResolution).toHaveBeenCalledWith(1, expect.objectContaining({ learning_outcome_status: undefined }));
    });
  });
});

describe('CaseDetailsPage scroll position', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('opens at the top, not where the previous page was scrolled to', async () => {
    const scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
    vi.mocked(api.getCase).mockResolvedValue(baseCase());

    renderPage();

    await screen.findByRole('tab', { name: /Resolution/i });
    expect(scrollTo).toHaveBeenCalledWith(0, 0);
  });
});

describe('CaseDetailsPage for a case that does not exist (QA-19)', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('says the case does not exist instead of a generic load failure', async () => {
    vi.mocked(api.getCase).mockRejectedValue(new ApiError(404, 'case not found'));
    renderPage();

    expect(await screen.findByText(/Case #1 doesn't exist/)).toBeTruthy();
    expect(screen.queryByText('Failed to load case details')).toBeNull();
  });

  it('offers a retry when loading failed for another reason', async () => {
    vi.mocked(api.getCase).mockRejectedValue(new ApiError(503, 'database unavailable'));
    renderPage();

    expect(await screen.findByText('Failed to load case details')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy();
  });
});

describe('CaseDetailsPage similar cases', () => {
  afterEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getSimilarCases).mockResolvedValue({ source_case_id: 1, matches: [] } as unknown as Awaited<ReturnType<typeof api.getSimilarCases>>);
  });

  it('says memory is unavailable at once, instead of retrying into a generic error (QA-34)', async () => {
    vi.mocked(api.getCase).mockResolvedValue(baseCase());
    vi.mocked(api.getSimilarCases).mockRejectedValue(
      new ApiError(503, "Operational memory is unavailable right now: Qdrant can't be reached. Details are in the server log (error 1a2b3c4d)."),
    );
    renderPage();

    fireEvent.click(await screen.findByRole('tab', { name: /Similar Cases/i }));

    expect(await screen.findByText(/Similar cases can't be searched right now: Operational memory is unavailable/)).toBeTruthy();
    expect(screen.queryByText('Failed to load similar cases')).toBeNull();
    expect(api.getSimilarCases).toHaveBeenCalledTimes(1);
  });
});

describe('CaseDetailsPage workflow (QA-40)', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  async function stepIsTicked(name: string) {
    const chip = (await screen.findByText(name)).closest('.MuiChip-root') as HTMLElement;
    return within(chip).queryByTestId('CheckCircleRoundedIcon') !== null;
  }

  it('does not tick Knowledge published for an open case that memory indexed on creation', async () => {
    vi.mocked(api.getCase).mockResolvedValue(baseCase({ memory_status: 'indexed' }));
    renderPage();

    expect(await stepIsTicked('6. Knowledge published')).toBe(false);
    expect(await stepIsTicked('1. Finding reviewed')).toBe(true);
  });

  it('ticks Knowledge published once the resolution is recorded and the case is indexed', async () => {
    vi.mocked(api.getCase).mockResolvedValue(
      baseCase({ memory_status: 'indexed', outcome_status: 'resolved', outcome_summary: 'Rolled back the deploy.' }),
    );
    renderPage();

    expect(await stepIsTicked('6. Knowledge published')).toBe(true);
  });

  it('offers every outcome the API accepts', async () => {
    vi.mocked(api.getCase).mockResolvedValue(baseCase());
    renderPage();
    const panel = await openResolutionPanel();

    fireEvent.mouseDown(within(panel).getAllByRole('combobox')[0]);
    const options = (await screen.findAllByRole('option')).map((option) => option.textContent);

    expect(options).toEqual(['Pending', 'In Progress', 'Mitigated', 'Resolved', 'Escalated', "Won't fix"]);
  });

  it("shows the saved outcome of a won't-fix case instead of a blank field", async () => {
    vi.mocked(api.getCase).mockResolvedValue(baseCase({ outcome_status: 'won_t_fix' }));
    renderPage();
    const panel = await openResolutionPanel();

    expect(within(panel).getAllByRole('combobox')[0].textContent).toBe("Won't fix");
  });
});

describe('CaseDetailsPage AI drafts', () => {
  const aiOn = { enabled: true, provider: 'ollama', model: 'qwen2.5:3b', endpoint: null, api_key_set: null, active: true, issue: null };

  afterEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.aiStatus).mockResolvedValue({ ...aiOn, enabled: false, active: false });
  });

  async function openTab(name: RegExp) {
    fireEvent.click(await screen.findByRole('tab', { name }));
    return screen.getByRole('tabpanel');
  }

  it('fills the root cause from the case, shows what it was drafted from, and undoes', async () => {
    vi.mocked(api.aiStatus).mockResolvedValue(aiOn);
    vi.mocked(api.getCase).mockResolvedValue(baseCase());
    vi.mocked(api.suggestRca).mockResolvedValue({
      available: true,
      draft: 'A retry loop in v2.3 may not release DB connections (OPS-412).',
      sources: [{ kind: 'ticket_comment', label: 'Ticket comment, Sam', detail: "connections aren't released on timeout" }],
    });

    renderPage();
    const panel = await openTab(/Root Cause/i);
    fireEvent.click(await within(panel).findByRole('button', { name: /Draft from case/i }));

    const box = within(panel).getByLabelText('Root cause summary');
    await waitFor(() => expect(box).toHaveValue('A retry loop in v2.3 may not release DB connections (OPS-412).'));
    expect(within(panel).getByTestId('case-draft-chip')).toBeInTheDocument();
    expect(within(panel).getByTestId('case-draft-sources')).toHaveTextContent('Ticket comment, Sam');
    expect(api.updateRCA).not.toHaveBeenCalled();

    fireEvent.click(within(panel).getByRole('button', { name: 'Undo draft' }));
    expect(box).toHaveValue('');
    expect(within(panel).queryByTestId('case-draft-chip')).not.toBeInTheDocument();
  });

  it('asks before replacing text already in the box', async () => {
    vi.mocked(api.aiStatus).mockResolvedValue(aiOn);
    vi.mocked(api.getCase).mockResolvedValue(baseCase({ root_cause_summary: 'My own words.' }));

    renderPage();
    const panel = await openTab(/Root Cause/i);
    fireEvent.click(await within(panel).findByRole('button', { name: /Draft from case/i }));

    const dialog = await screen.findByRole('dialog', { name: 'Replace your text?' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Keep my text' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(api.suggestRca).not.toHaveBeenCalled();
    expect(within(panel).getByLabelText('Root cause summary')).toHaveValue('My own words.');
  });

  it('says when there is nothing on the case to draft from', async () => {
    vi.mocked(api.aiStatus).mockResolvedValue(aiOn);
    vi.mocked(api.getCase).mockResolvedValue(baseCase());
    vi.mocked(api.suggestRca).mockResolvedValue({ available: false, reason_code: 'not_enough' });

    renderPage();
    const panel = await openTab(/Root Cause/i);
    fireEvent.click(await within(panel).findByRole('button', { name: /Draft from case/i }));

    expect(await within(panel).findByText(/Not enough on this case to draft from yet/)).toBeInTheDocument();
    expect(within(panel).getByLabelText('Root cause summary')).toHaveValue('');
  });

  it('fills both resolution boxes', async () => {
    vi.mocked(api.aiStatus).mockResolvedValue(aiOn);
    vi.mocked(api.getCase).mockResolvedValue(baseCase());
    vi.mocked(api.suggestResolution).mockResolvedValue({
      available: true,
      draft: 'Rolled back to v2.2; latency normal.',
      corrective_action: 'Rolled back. Still open: fix the retry loop.',
      sources: [{ kind: 'note', label: 'Note', detail: 'Rolled back to v2.2' }],
    });

    renderPage();
    const panel = await openTab(/Resolution/i);
    fireEvent.click(await within(panel).findByRole('button', { name: /Draft from case/i }));

    await waitFor(() => expect(within(panel).getByLabelText('Outcome summary')).toHaveValue('Rolled back to v2.2; latency normal.'));
    expect(within(panel).getByLabelText('Corrective action')).toHaveValue('Rolled back. Still open: fix the retry loop.');
  });

  it('with AI off there is no button, and admins see how to turn it on', async () => {
    vi.mocked(api.getCase).mockResolvedValue(baseCase());

    renderPage();
    const panel = await openTab(/Root Cause/i);

    expect(await within(panel).findByTestId('enable-ai-hint')).toHaveTextContent('Turn on AI to draft the root cause');
    expect(within(panel).queryByRole('button', { name: /Draft from case/i })).not.toBeInTheDocument();
  });
});

describe('CaseDetailsPage Publish Knowledge write-up', () => {
  const aiOn = { enabled: true, provider: 'ollama', model: 'qwen2.5:3b', endpoint: null, api_key_set: null, active: true, issue: null };
  const timeline = {
    events: [
      { time: '2026-10-20T14:05:00Z', kind: 'deploy' as const, text: 'Deploy v2.3 on checkout', who: null },
      { time: '2026-10-20T14:35:00Z', kind: 'ticket_comment' as const, text: 'v2.3 added a retry loop', who: 'Sam' },
      { time: '2026-10-20T15:10:00Z', kind: 'resolved' as const, text: 'Resolved', who: 'priya' },
    ],
    time_to_fix_minutes: 65,
    memory_text: 'Operational Case\nWrite-up:\nSummary: rolled back.',
  };

  afterEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.aiStatus).mockResolvedValue({ ...aiOn, enabled: false, active: false });
  });

  async function openPublish() {
    fireEvent.click(await screen.findByRole('tab', { name: /Publish Knowledge/i }));
    return screen.getByRole('tabpanel');
  }

  it('shows the timeline built from the case, with the time to fix', async () => {
    vi.mocked(api.getCase).mockResolvedValue(baseCase());
    vi.mocked(api.caseTimeline).mockResolvedValue(timeline);

    renderPage();
    const panel = await openPublish();

    const list = await within(panel).findByTestId('case-timeline');
    expect(list).toHaveTextContent('Deploy v2.3 on checkout');
    expect(list).toHaveTextContent('"v2.3 added a retry loop" · Sam, ticket');
    expect(list).toHaveTextContent('Time to fix: 1 h 5 min from the first finding.');
  });

  it('drafts the write-up, then Save and publish saves it and publishes the case', async () => {
    vi.mocked(api.aiStatus).mockResolvedValue(aiOn);
    vi.mocked(api.getCase).mockResolvedValue(baseCase({ root_cause_summary: 'Retry loop.' }));
    vi.mocked(api.caseTimeline).mockResolvedValue(timeline);
    vi.mocked(api.suggestWriteup).mockResolvedValue({ available: true, draft: 'Summary: rolled back.', sources: [{ kind: 'root_cause', label: 'Saved root cause' }] });
    vi.mocked(api.updateWriteup).mockResolvedValue(baseCase({ writeup: 'Summary: rolled back.' }));
    vi.mocked(api.indexCaseMemory).mockResolvedValue({ case_id: 1, memory_status: 'indexed' });

    renderPage();
    const panel = await openPublish();
    fireEvent.click(await within(panel).findByRole('button', { name: /Draft write-up/i }));
    await waitFor(() => expect(within(panel).getByLabelText('Summary and lessons')).toHaveValue('Summary: rolled back.'));
    expect(api.updateWriteup).not.toHaveBeenCalled();

    fireEvent.click(within(panel).getByRole('button', { name: 'Save and publish' }));
    await waitFor(() => expect(api.indexCaseMemory).toHaveBeenCalledWith(1));
    expect(api.updateWriteup).toHaveBeenCalledWith(1, 'Summary: rolled back.');
  });

  it('shows a saved write-up read-only until Edit', async () => {
    vi.mocked(api.getCase).mockResolvedValue(baseCase({ writeup: 'Summary: rolled back.' }));
    renderPage();
    const panel = await openPublish();

    expect(await within(panel).findByTestId('case-writeup-saved')).toHaveTextContent('Summary: rolled back.');
    expect(within(panel).queryByLabelText('Summary and lessons')).not.toBeInTheDocument();
  });

  it('says to save a root cause first when there is nothing to draft from', async () => {
    vi.mocked(api.aiStatus).mockResolvedValue(aiOn);
    vi.mocked(api.getCase).mockResolvedValue(baseCase());
    vi.mocked(api.suggestWriteup).mockResolvedValue({ available: false, reason_code: 'not_enough' });

    renderPage();
    const panel = await openPublish();
    fireEvent.click(await within(panel).findByRole('button', { name: /Draft write-up/i }));

    expect(await within(panel).findByText(/Save a root cause or a resolution first/)).toBeInTheDocument();
  });
});

describe('CaseDetailsPage Investigation tab', () => {
  const investigation = {
    id: 10, finding_id: 10, service: 'payments-service', status: 'done', ending: 'nothing_found', ending_detail: null,
    summary: 'No recorded change explains the gap.', question: null, round: 1, checks_used: 3, check_budget: 15, case_id: 1,
    model: 'test-model', started_by: 'priya', context_note: null, skipped_sources: [], created_at: null, updated_at: null,
    checks: [], steps: [],
  };

  afterEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.investigations).mockResolvedValue([]);
  });

  async function openInvestigationTab() {
    fireEvent.click(await screen.findByRole('tab', { name: /^Investigation$/i }));
    return screen.getByRole('tabpanel');
  }

  it('without a guided investigation, shows the note form as before and saves what was typed', async () => {
    vi.mocked(api.getCase).mockResolvedValue(baseCase());
    vi.mocked(api.updateInvestigation).mockResolvedValue(baseCase());
    renderPage();

    const panel = await openInvestigationTab();
    await waitFor(() => expect(api.investigations).toHaveBeenCalledWith({ case_id: 1 }));
    expect(within(panel).queryByText('Guided investigation')).not.toBeInTheDocument();
    expect(within(panel).queryByTestId('use-as-note')).not.toBeInTheDocument();
    fireEvent.change(within(panel).getByLabelText('Investigation note'), { target: { value: 'Checked the pool.' } });
    fireEvent.click(within(panel).getByRole('button', { name: /Save Investigation/i }));

    await waitFor(() => expect(api.updateInvestigation).toHaveBeenCalledWith(1, { investigation_status: 'not_started', investigation_note: 'Checked the pool.' }));
  });

  it('Use as note puts the draft below what was already typed, and nothing is saved until Save', async () => {
    vi.mocked(api.getCase).mockResolvedValue(baseCase());
    vi.mocked(api.investigations).mockResolvedValue([investigation] as never);
    vi.mocked(api.getInvestigation).mockResolvedValue(investigation as never);
    vi.mocked(api.investigationNoteDraft).mockResolvedValue({ text: 'Guided investigation #10 · suggested, not confirmed\n\nWhat I found: ' });
    renderPage();

    const panel = await openInvestigationTab();
    const box = within(panel).getByLabelText('Investigation note');
    fireEvent.change(box, { target: { value: 'My own line.' } });
    fireEvent.click(await within(panel).findByTestId('use-as-note'));

    await waitFor(() => expect(box).toHaveValue('My own line.\n\nGuided investigation #10 · suggested, not confirmed\n\nWhat I found: '));
    expect(api.investigationNoteDraft).toHaveBeenCalledWith(10);
    expect(api.updateInvestigation).not.toHaveBeenCalled();
  });
});

describe('CaseDetailsPage next step with a guided investigation', () => {
  const investigation = {
    id: 24, finding_id: 10, service: 'payments-service', status: 'done', ending: 'found', ending_detail: null,
    summary: 'Everything dropped at 22:02.', question: null, round: 1, checks_used: 8, check_budget: 15, case_id: 1,
    model: 'test-model', started_by: 'priya', context_note: null, skipped_sources: [], created_at: null, updated_at: null,
    checks: [{ ref: 'c1', round: 1, tool: 'query_range', purpose: 'p', query: 'q', ok: true, result: 'r', at: null }],
    steps: [
      { id: 1, round: 1, position: 1, kind: 'your_step', status: 'todo', title: 'Check request volume at 22:02', why: null, result: null, evidence: [], unverified: false, mark: null, note: null, marked_by: null },
      { id: 2, round: 1, position: 2, kind: 'checked', status: 'worth_a_look', title: 'Latency and CPU dropped together', why: null, result: null, evidence: ['c1'], unverified: false, mark: null, note: null, marked_by: null },
      { id: 3, round: 1, position: 3, kind: 'checked', status: 'ruled_out', title: 'No deploy', why: null, result: null, evidence: ['c1'], unverified: false, mark: null, note: null, marked_by: null },
    ],
  };
  const saved = { timestamp: '2026-11-08T13:00:00Z', note: 'Saved guided investigation #24 to this case.', investigation_id: 24 };

  afterEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.investigations).mockResolvedValue([]);
  });

  it('asks you to go through the investigation, and its saved line does not count as your note', async () => {
    vi.mocked(api.getCase).mockResolvedValue(baseCase({ investigation_status: 'in_progress', investigation_notes: [saved], finding_snapshot: { ...baseCase().finding_snapshot, signal_ids: ['s1'] } }));
    vi.mocked(api.investigations).mockResolvedValue([investigation] as never);
    vi.mocked(api.getInvestigation).mockResolvedValue(investigation as never);
    renderPage();

    const next = await screen.findByTestId('guided-next-action');
    expect(next).toHaveTextContent('Go through guided investigation #24');
    await waitFor(() => expect(next).toHaveTextContent('It ran 1 check and left you 1 step.'));
    const listed = within(next).getAllByText(/Latency and CPU dropped together|Check request volume at 22:02/).map((node) => node.textContent);
    expect(listed).toEqual(['Latency and CPU dropped together', 'Check request volume at 22:02']);
    expect(within(next).queryByText('No deploy')).not.toBeInTheDocument();
    expect(screen.getByText('Go through guided investigation #24, then use it as your note.')).toBeInTheDocument();

    fireEvent.click(within(next).getByRole('button', { name: 'Open the investigation' }));
    expect(await screen.findByRole('tab', { name: /^Investigation$/i })).toHaveAttribute('aria-selected', 'true');
  });

  it('once you saved a note of your own, the case moves on as before', async () => {
    vi.mocked(api.getCase).mockResolvedValue(baseCase({ investigation_status: 'in_progress', investigation_notes: [saved, { timestamp: '2026-11-08T13:10:00Z', note: 'Request volume fell at 22:02.' }] }));
    vi.mocked(api.investigations).mockResolvedValue([investigation] as never);
    renderPage();

    expect(await screen.findByText('Document the root cause and confidence.')).toBeInTheDocument();
    expect(screen.queryByTestId('guided-next-action')).not.toBeInTheDocument();
  });
});
