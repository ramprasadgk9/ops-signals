import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/queries';
import type { Finding } from '../types';
import type { Investigation, InvestigationStartInfo, ServiceNote } from '../utils/investigation';
import { InvestigateDialog } from './InvestigateDialog';

vi.mock('../api/queries', () => ({
  api: {
    me: vi.fn(),
    investigationStartInfo: vi.fn(),
    serviceNoteSuggestions: vi.fn(),
    saveServiceNote: vi.fn(),
    startInvestigation: vi.fn(),
    getInvestigation: vi.fn(),
    markInvestigationStep: vi.fn(),
    continueInvestigation: vi.fn(),
    stopInvestigation: vi.fn(),
    createCase: vi.fn(),
    attachInvestigationToCase: vi.fn(),
  },
}));

const mocked = vi.mocked(api);

const finding = {
  id: 11,
  service: 'search',
  metric_name: 'request_latency_ms',
  title: 'Search latency spiked',
  summary: '',
  category: 'behavior_change',
  health_status: 'critical',
  importance_score: 0.9,
  investigation_priority: 1,
  signal_ids: [],
  comparison_json: {},
  connection_id: 'default',
  source: 'prometheus',
} as Finding;

const emptyNote: ServiceNote = {
  service: 'search', exists: false, depends_on: [], behaviours: [], dismissed: [], owner: null, channel: null, runbook_url: null, updated_by: null, updated_at: null,
};

const info = (overrides: Partial<InvestigationStartInfo> = {}): InvestigationStartInfo => ({
  finding_id: 11, eligible: true, reason: null, ai_on: true, service: 'search', connection_id: 'default', connection_name: 'prod-metrics', has_query: true, note: emptyNote, latest: null,
  ...overrides,
});

const investigation: Investigation = {
  id: 5, finding_id: 11, service: 'search', status: 'done', ending: 'found', ending_detail: null,
  summary: 'Search started waiting for elasticsearch at 10:09. Look there next.', question: null, round: 1, checks_used: 2, check_budget: 15,
  case_id: null, model: 'scripted', started_by: 'priya', context_note: null, skipped_sources: [], created_at: null, updated_at: null,
  checks: [{ ref: 'c1', round: 1, tool: 'query_range', purpose: 'Waiting for elasticsearch?', query: 'es_wait_seconds', ok: true, result: '1 series: rose at 10:09.', at: null }],
  steps: [
    { id: 21, round: 1, position: 1, kind: 'checked', status: 'worth_a_look', title: 'Waiting for elasticsearch', why: 'It rose a minute before latency.', result: 'Wait rose at 10:09.', evidence: ['c1'], unverified: false, mark: null, note: null, marked_by: null },
    { id: 22, round: 1, position: 2, kind: 'checked', status: 'ruled_out', title: 'Traffic jumped', why: null, result: null, evidence: [], unverified: true, mark: null, note: null, marked_by: null },
  ],
};

function renderDialog() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <InvestigateDialog finding={finding} open onClose={vi.fn()} />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  mocked.me.mockRejectedValue(new Error('no sign-in'));
  mocked.serviceNoteSuggestions.mockResolvedValue([{ name: 'elasticsearch', kind: 'database', label: 'db_system="elasticsearch"' }]);
  mocked.getInvestigation.mockResolvedValue(investigation);
});

describe('InvestigateDialog before Start', () => {
  it('asks what search depends on the first time, then saves the notes and starts', async () => {
    mocked.investigationStartInfo.mockResolvedValue(info());
    mocked.saveServiceNote.mockResolvedValue({ ...emptyNote, exists: true });
    mocked.startInvestigation.mockResolvedValue(investigation);
    renderDialog();

    expect(await screen.findByText('Help it start in the right place')).toBeInTheDocument();
    const suggestion = await screen.findByTestId('dependency-suggestion');
    fireEvent.click(within(suggestion).getByRole('button', { name: 'Add' }));
    fireEvent.click(screen.getByLabelText(/Past cases/));
    fireEvent.change(screen.getByLabelText('Anything about today?'), { target: { value: 'The index rebuild ran late.' } });
    fireEvent.click(screen.getByTestId('start-investigation'));

    await waitFor(() => expect(mocked.startInvestigation).toHaveBeenCalled());
    expect(mocked.saveServiceNote).toHaveBeenCalledWith('search', expect.objectContaining({ depends_on: [{ name: 'elasticsearch', kind: 'database' }] }));
    expect(mocked.startInvestigation).toHaveBeenCalledWith({ finding_id: 11, note: 'The index rebuild ran late.', save_note: false, skipped_sources: ['cases'] });
    expect(await screen.findByText('Found where to look')).toBeInTheDocument();
  });

  it('explains how to turn on AI when it is off', async () => {
    mocked.investigationStartInfo.mockResolvedValue(info({ ai_on: false }));
    renderDialog();

    expect(await screen.findByText('Investigate needs an AI provider')).toBeInTheDocument();
    expect(screen.queryByTestId('start-investigation')).not.toBeInTheDocument();
  });

  it('says why a finding cannot be investigated', async () => {
    mocked.investigationStartInfo.mockResolvedValue(info({ eligible: false, reason: 'This finding came from an uploaded file or OTLP data, so there\'s no query to run again.' }));
    renderDialog();

    expect(await screen.findByText(/uploaded file/)).toBeInTheDocument();
  });
});

describe('InvestigateDialog steps', () => {
  beforeEach(() => {
    mocked.investigationStartInfo.mockResolvedValue(info({ latest: investigation }));
  });

  it('opens on the latest investigation and flags a step nothing backs', async () => {
    renderDialog();

    expect(await screen.findByTestId('investigation-summary')).toHaveTextContent('Look there next.');
    expect(screen.getAllByTestId('investigation-step')).toHaveLength(2);
    expect(screen.getByText(/Not checked: no check or past case/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Show query' }));
    expect(screen.getByText(/es_wait_seconds/)).toBeInTheDocument();
  });

  it('marks a step and saves the investigation to a new case', async () => {
    mocked.markInvestigationStep.mockResolvedValue({ ...investigation, steps: [{ ...investigation.steps[0], mark: 'found' }, investigation.steps[1]] });
    mocked.createCase.mockResolvedValue({ case_id: 31, finding_id: 11, case_status: 'open', memory_status: 'not_indexed' });
    mocked.attachInvestigationToCase.mockResolvedValue({ ...investigation, case_id: 31 });
    renderDialog();

    const first = (await screen.findAllByTestId('investigation-step'))[0];
    fireEvent.click(within(first).getByRole('button', { name: 'Found something' }));
    await waitFor(() => expect(mocked.markInvestigationStep).toHaveBeenCalledWith(5, 21, { mark: 'found', note: null }));
    expect(await within(screen.getAllByTestId('investigation-step')[0]).findByText('You found something')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('save-to-case'));
    await waitFor(() => expect(mocked.attachInvestigationToCase).toHaveBeenCalledWith(5, 31));
    expect(await screen.findByRole('link', { name: 'Open case #31' })).toBeInTheDocument();
  });

  it('sends what the engineer says as the next round', async () => {
    mocked.continueInvestigation.mockResolvedValue({ ...investigation, status: 'running', ending: null, round: 2 });
    renderDialog();

    fireEvent.change(await screen.findByLabelText('Ask or tell it something'), { target: { value: 'The rebuild is off today.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() => expect(mocked.continueInvestigation).toHaveBeenCalledWith(5, 'The rebuild is off today.'));
    expect(await screen.findByTestId('investigation-running')).toBeInTheDocument();
  });
});
