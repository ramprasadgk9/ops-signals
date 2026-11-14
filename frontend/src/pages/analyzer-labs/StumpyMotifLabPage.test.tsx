import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { StumpyMotifLabPage } from './StumpyMotifLabPage';
import { api } from '../../api/queries';

vi.mock('../../api/queries', () => ({
  api: {
    analyzerSettings: vi.fn().mockResolvedValue({ analyzers: [] }),
    services: vi.fn().mockResolvedValue([]),
    runCsvValidation: vi.fn().mockResolvedValue({ findings: [], signals: [] }),
  },
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <StumpyMotifLabPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.clearAllMocks());

describe('StumpyMotifLabPage', () => {
  it('asks for motif mode, since the shipped settings it merges into run discord mode', async () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: /Run Analyzer/ }));
    await waitFor(() => expect(api.runCsvValidation).toHaveBeenCalled());
    const form = vi.mocked(api.runCsvValidation).mock.calls[0][0] as FormData;
    const overrides = JSON.parse(String(form.get('analyzer_overrides')));
    expect(overrides.stumpy.implementation).toMatchObject({ mode: 'motif', window_size: 20, motif_count: 1 });
  });
});
