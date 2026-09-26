import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { api } from '../../../api/queries';
import { DocsCheckPage } from '../../../pages/DocsCheckPage';
import type { DocsCoverage, KnowledgeStatus } from '../../../types';

vi.mock('../../../api/queries', () => ({
  api: {
    knowledgeStatus: vi.fn(),
    docsCoverage: vi.fn(),
    flaggedQuestions: vi.fn(),
    draftDocQuestions: vi.fn(),
    evaluateDocQuestion: vi.fn(),
    saveDocTests: vi.fn(),
    updateAssistantFeedback: vi.fn(),
  },
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DocsCheckPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const coverage: DocsCoverage = {
  golden_available: true,
  total_docs: 2,
  covered_docs: 1,
  docs: [
    { source_path: 'docs/flags.md', title: 'Feature flags', section_count: 3, test_count: 0, untested_sections: ['Enabling a flag', 'Scope', 'History'], recently: 'added' },
    { source_path: 'docs/security-model.md', title: 'Security model', section_count: 5, test_count: 3, untested_sections: ['Known limitations'], recently: null },
  ],
};

function status(authoring: boolean): KnowledgeStatus {
  return { collection_exists: true, vector_count: 10, document_count: 2, pending_changes: null, docs_authoring_enabled: authoring, last_bootstrap: null };
}

describe('Docs check', () => {
  beforeEach(() => {
    vi.mocked(api.knowledgeStatus).mockResolvedValue(status(true));
    vi.mocked(api.docsCoverage).mockResolvedValue(coverage);
    vi.mocked(api.flaggedQuestions).mockResolvedValue([]);
    vi.mocked(api.saveDocTests).mockImplementation(async (tests, dryRun) => ({ saved_ids: tests.map((_, index) => `id-${index}`), yaml: '  - id: flags-scope', path: 'benchmark/assistant/golden_questions.yml', written: !dryRun }));
  });
  afterEach(() => vi.clearAllMocks());

  it('lists docs by test coverage, new docs first', async () => {
    renderPage();

    expect(await screen.findByText('1 of 2')).toBeInTheDocument();
    expect(screen.getAllByText('docs/flags.md')[0]).toBeInTheDocument();
    expect(screen.getByText('New')).toBeInTheDocument();
    expect(screen.getByText(/No tests · 3 of 3 sections untested/)).toBeInTheDocument();
  });

  it('drafts, asks, judges and saves a question - a wrong answer as a known gap', async () => {
    vi.mocked(api.draftDocQuestions).mockResolvedValue([
      { source_path: 'docs/flags.md', section: 'Scope', question: 'can i limit a flag to one service', contains: ['service: checkout-api'], drafted_by: 'gemma3:4b' },
    ]);
    vi.mocked(api.evaluateDocQuestion).mockResolvedValue({
      cited_expected: false,
      rank: null,
      cited: [{ source_path: 'README.md', section: '6.1 Prerequisites', reference: 'README.md#61-prerequisites', quote: 'Python 3.11' }],
      answer: 'a',
      ai_synthesis_used: false,
    });
    renderPage();
    await screen.findByText('1 of 2');

    fireEvent.click(screen.getByRole('button', { name: 'Draft questions' }));
    expect(await screen.findByDisplayValue('can i limit a flag to one service')).toBeInTheDocument();
    expect(screen.getByText('Drafted by gemma3:4b')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Ask' }));
    expect(await screen.findByText('Cited README.md > 6.1 Prerequisites instead')).toBeInTheDocument();
    expect(api.evaluateDocQuestion).toHaveBeenCalledWith({ question: 'can i limit a flag to one service', source_path: 'docs/flags.md', section: 'Scope' });

    fireEvent.click(screen.getByRole('button', { name: 'Wrong' }));
    expect(screen.getByLabelText('Save as known gap')).toBeChecked();
    await waitFor(() => expect(api.saveDocTests).toHaveBeenCalledWith(
      [{ question: 'can i limit a flag to one service', source_path: 'docs/flags.md', section: 'Scope', contains: ['service: checkout-api'], known_gap: true, feedback_ids: [] }],
      true,
    ));

    fireEvent.click(await screen.findByRole('button', { name: 'Save 1 test' }));

    expect(await screen.findByText(/Saved 1 to benchmark\/assistant\/golden_questions\.yml/)).toBeInTheDocument();
    expect(api.saveDocTests).toHaveBeenLastCalledWith(expect.any(Array), false);
  });

  it('brings a flagged question over with its feedback ids', async () => {
    vi.mocked(api.flaggedQuestions).mockResolvedValue([
      { question: 'how do i scope a flag', count: 2, reasons: { wrong_section: 2 }, cited: [], feedback_ids: [4, 5], last_flagged_at: '' },
    ]);
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: 'Add as test' }));

    expect(await screen.findByDisplayValue('how do i scope a flag')).toBeInTheDocument();
    expect(screen.getByText(/From user feedback - flagged 2×/)).toBeInTheDocument();
  });

  it('explains that saving needs file writes when they are off', async () => {
    vi.mocked(api.knowledgeStatus).mockResolvedValue(status(false));
    renderPage();

    expect(await screen.findByText(/needs a local checkout started with/)).toBeInTheDocument();
    expect(api.flaggedQuestions).not.toHaveBeenCalled();
  });
});
