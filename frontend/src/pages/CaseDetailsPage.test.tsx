import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
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
    aiStatus: vi.fn().mockResolvedValue({ enabled: false, provider: 'noop', model: null, endpoint: null, api_key_set: null, active: false, issue: null }),
    suggestRca: vi.fn(),
    suggestResolution: vi.fn(),
    caseTimeline: vi.fn().mockResolvedValue({ events: [], time_to_fix_minutes: null, memory_text: 'Operational Case' }),
    updateWriteup: vi.fn(),
    suggestWriteup: vi.fn(),
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

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/cases/1']}>
        <Routes>
          <Route path="/cases/:caseId" element={<CaseDetailsPage />} />
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
