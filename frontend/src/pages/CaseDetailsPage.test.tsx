import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { CaseDetailsPage } from './CaseDetailsPage';
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
