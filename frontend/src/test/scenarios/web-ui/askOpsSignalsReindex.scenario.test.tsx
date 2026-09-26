import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { api } from '../../../api/queries';
import { MemoryChatPage } from '../../../pages/MemoryChatPage';

vi.mock('../../../api/queries', () => ({
  api: {
    assistantChat: vi.fn(),
    reindexKnowledge: vi.fn(),
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

const result = {
  added: ['docs/new-feature.md'],
  changed: ['docs/security-model.md'],
  removed: [],
  unchanged_documents: 70,
  chunks_embedded: 14,
  forced: false,
  started_at: '2026-09-26T20:00:00+00:00',
  duration_ms: 1200,
};

describe('Ask Ops Signals reindex', () => {
  afterEach(() => vi.clearAllMocks());

  it('reindexes docs and says what changed', async () => {
    vi.mocked(api.reindexKnowledge).mockResolvedValue(result);
    renderPage();

    fireEvent.click(screen.getByRole('button', { name: /reindex docs/i }));

    expect(await screen.findByText(/added docs\/new-feature\.md, updated docs\/security-model\.md\. 14 sections indexed, 70 documents unchanged \(1\.2s\)\./)).toBeInTheDocument();
    expect(api.reindexKnowledge).toHaveBeenCalledTimes(1);
  });

  it('says so when docs are already up to date', async () => {
    vi.mocked(api.reindexKnowledge).mockResolvedValue({ ...result, added: [], changed: [], chunks_embedded: 0 });
    renderPage();

    fireEvent.click(screen.getByRole('button', { name: /reindex docs/i }));

    expect(await screen.findByText(/Docs are up to date - 70 documents unchanged/)).toBeInTheDocument();
  });

  it('shows the error when reindexing fails', async () => {
    vi.mocked(api.reindexKnowledge).mockRejectedValue(new Error('Assistant knowledge bootstrap is not initialized'));
    renderPage();

    fireEvent.click(screen.getByRole('button', { name: /reindex docs/i }));

    expect(await screen.findByText(/Reindex failed: Assistant knowledge bootstrap is not initialized/)).toBeInTheDocument();
  });
});
