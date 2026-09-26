import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { api } from '../../../api/queries';
import { MemoryChatPage } from '../../../pages/MemoryChatPage';
import type { AssistantChatResponse, KnowledgeReindexResult, KnowledgeStatus } from '../../../types';

vi.mock('../../../api/queries', () => ({
  api: {
    assistantChat: vi.fn(),
    reindexKnowledge: vi.fn(),
    knowledgeStatus: vi.fn(),
    flaggedQuestions: vi.fn(),
    sendAssistantFeedback: vi.fn(),
    updateAssistantFeedback: vi.fn(),
    starterQuestions: vi.fn(),
    runCsvUpload: vi.fn(),
  },
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <MemoryChatPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const result: KnowledgeReindexResult = {
  added: ['docs/new-feature.md'],
  changed: ['docs/security-model.md'],
  removed: [],
  unchanged_documents: 63,
  chunks_embedded: 14,
  forced: false,
  started_at: '2026-09-26T20:00:00+00:00',
  duration_ms: 1200,
};

function status(overrides: Partial<KnowledgeStatus> = {}): KnowledgeStatus {
  return {
    collection_exists: true,
    vector_count: 716,
    document_count: 65,
    pending_changes: { added: [], changed: [], removed: [] },
    docs_authoring_enabled: false,
    last_bootstrap: null,
    ...overrides,
  };
}

const answer: AssistantChatResponse = {
  conversation_id: 'conv-1',
  intent: 'documentation',
  routes: ['DOCUMENT_SEARCH'],
  knowledge_used: ['Documentation'],
  answer: 'From Security model > Turning on authentication:\n> Set one shared token:',
  ai_synthesis_used: false,
  limitations: [],
  suggested_questions: [],
  sources: [
    { source_type: 'app_documentation', title: 'Security model', score: 0.61, reference: 'docs/security-model.md#turning-on-authentication', section: 'Turning on authentication', quote: 'Set one shared token:' },
  ],
  evidence_groups: [],
};

const reindexButton = () => screen.getByRole('button', { name: /^reindex docs$/i });

describe('Ask Ops Signals reindex', () => {
  beforeEach(() => {
    vi.mocked(api.starterQuestions).mockResolvedValue({ has_data: false, questions: [] });
    vi.mocked(api.knowledgeStatus).mockResolvedValue(status());
    vi.mocked(api.flaggedQuestions).mockResolvedValue([]);
  });
  afterEach(() => vi.clearAllMocks());

  it('says the reindex is done and what changed', async () => {
    vi.mocked(api.reindexKnowledge).mockResolvedValue(result);
    renderPage();

    fireEvent.click(reindexButton());

    expect(await screen.findByText('Docs reindexed just now. Answers now include your changes.')).toBeInTheDocument();
    expect(screen.getByText(/New: docs\/new-feature\.md · Updated: docs\/security-model\.md · 63 other docs unchanged · took 1\.2s/)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /test the new docs/i })).not.toBeInTheDocument();
  });

  it('offers to test new docs only where docs can be authored', async () => {
    vi.mocked(api.knowledgeStatus).mockResolvedValue(status({ docs_authoring_enabled: true }));
    vi.mocked(api.reindexKnowledge).mockResolvedValue(result);
    renderPage();
    await waitFor(() => expect(api.knowledgeStatus).toHaveBeenCalled());

    fireEvent.click(reindexButton());

    expect(await screen.findByRole('link', { name: /test the new docs/i })).toHaveAttribute('href', '/assistant/docs-check');
  });

  it('says so when docs are already up to date', async () => {
    vi.mocked(api.reindexKnowledge).mockResolvedValue({ ...result, added: [], changed: [], chunks_embedded: 0 });
    renderPage();

    fireEvent.click(reindexButton());

    expect(await screen.findByText('Docs were already up to date. Nothing needed reindexing.')).toBeInTheDocument();
  });

  it('shows the error when reindexing fails', async () => {
    vi.mocked(api.reindexKnowledge).mockRejectedValue(new Error('Assistant knowledge bootstrap is not initialized'));
    renderPage();

    fireEvent.click(reindexButton());

    expect(await screen.findByText(/Reindex failed: Assistant knowledge bootstrap is not initialized/)).toBeInTheDocument();
  });

  it('points out docs that changed since the last read, and reindexes from the banner', async () => {
    vi.mocked(api.knowledgeStatus).mockResolvedValue(status({ pending_changes: { added: ['docs/new-feature.md'], changed: ['docs/security-model.md'], removed: [] } }));
    vi.mocked(api.reindexKnowledge).mockResolvedValue(result);
    renderPage();

    expect(await screen.findByText('2 docs changed')).toBeInTheDocument();
    expect(screen.getByText(/docs\/new-feature\.md, docs\/security-model\.md/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /reindex now/i }));

    expect(await screen.findByText('Docs reindexed just now. Answers now include your changes.')).toBeInTheDocument();
    expect(api.reindexKnowledge).toHaveBeenCalledTimes(1);
  });

  it('explains what Reindex docs is for', async () => {
    renderPage();

    fireEvent.click(screen.getByRole('button', { name: /what does reindex docs do/i }));

    expect(await screen.findByText(/you added or edited a doc and want answers to include it/)).toBeInTheDocument();
    expect(screen.getByText(/findings, cases and metrics are never touched/)).toBeInTheDocument();
  });
});

describe('Ask Ops Signals answer feedback', () => {
  beforeEach(() => {
    vi.mocked(api.starterQuestions).mockResolvedValue({ has_data: false, questions: [] });
    vi.mocked(api.knowledgeStatus).mockResolvedValue(status());
    vi.mocked(api.flaggedQuestions).mockResolvedValue([]);
    vi.mocked(api.assistantChat).mockResolvedValue(answer);
  });
  afterEach(() => vi.clearAllMocks());

  async function ask() {
    renderPage();
    fireEvent.click(screen.getByText('How do I turn on API authentication?'));
    await screen.findByText(/Did this answer your question/);
  }

  it('saves a thumbs-down with the question and what was cited, then the reason', async () => {
    vi.mocked(api.sendAssistantFeedback).mockResolvedValue({ id: 7, question: 'q', helpful: false, reason: null, status: 'open', created_at: '' });
    vi.mocked(api.updateAssistantFeedback).mockResolvedValue({ id: 7, question: 'q', helpful: false, reason: 'wrong_section', status: 'open', created_at: '' });
    await ask();

    fireEvent.click(screen.getByRole('button', { name: /no, it didn't/i }));
    fireEvent.click(await screen.findByText('Wrong section'));

    expect(await screen.findByText('Thanks - saved for review')).toBeInTheDocument();
    expect(api.sendAssistantFeedback).toHaveBeenCalledWith(expect.objectContaining({
      question: 'How do I turn on API authentication?',
      helpful: false,
      cited: ['docs/security-model.md#turning-on-authentication'],
    }));
    expect(api.updateAssistantFeedback).toHaveBeenCalledWith(7, { reason: 'wrong_section' });
  });

  it('a thumbs-up asks nothing more', async () => {
    vi.mocked(api.sendAssistantFeedback).mockResolvedValue({ id: 8, question: 'q', helpful: true, reason: null, status: 'open', created_at: '' });
    await ask();

    fireEvent.click(screen.getByRole('button', { name: /yes, it did/i }));

    expect(await screen.findByText('Thanks')).toBeInTheDocument();
    expect(screen.queryByText('What was wrong?')).not.toBeInTheDocument();
  });

  it('links flagged questions to Docs check where docs can be authored', async () => {
    vi.mocked(api.knowledgeStatus).mockResolvedValue(status({ docs_authoring_enabled: true }));
    vi.mocked(api.flaggedQuestions).mockResolvedValue([
      { question: 'how do i rotate the api token', count: 3, reasons: { wrong_section: 3 }, cited: [], feedback_ids: [1, 2, 3], last_flagged_at: '' },
    ]);
    renderPage();

    expect(await screen.findByRole('link', { name: /1 question flagged as not answered/i })).toHaveAttribute('href', '/assistant/docs-check');
  });
});

describe('Ask Ops Signals example questions', () => {
  beforeEach(() => {
    vi.mocked(api.knowledgeStatus).mockResolvedValue(status());
    vi.mocked(api.flaggedQuestions).mockResolvedValue([]);
  });
  afterEach(() => vi.clearAllMocks());

  it('offers a next step instead of system questions when nothing is analysed yet', async () => {
    vi.mocked(api.starterQuestions).mockResolvedValue({ has_data: false, questions: [] });
    renderPage();

    expect(await screen.findByText(/Nothing has been analysed yet/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Load demo data' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /connect a source/i })).toHaveAttribute('href', '/integrations');
    expect(screen.queryByText('What changed yesterday?')).not.toBeInTheDocument();
    expect(screen.getByText('Which analyzers are there and what does each find?')).toBeInTheDocument();
  });

  it('asks about the findings and cases this install actually has', async () => {
    vi.mocked(api.starterQuestions).mockResolvedValue({
      has_data: true,
      questions: ['What changed recently on payments-api?', 'Have we seen a case like "Slow checkout after deploy v2.3" before?'],
    });
    vi.mocked(api.assistantChat).mockResolvedValue(answer);
    renderPage();

    fireEvent.click(await screen.findByText('What changed recently on payments-api?'));

    await waitFor(() => expect(api.assistantChat).toHaveBeenCalledWith(expect.objectContaining({ message: 'What changed recently on payments-api?' })));
    expect(screen.queryByText(/Nothing has been analysed yet/)).not.toBeInTheDocument();
  });
});
