import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SystemPage } from './SystemPage';
import { api } from '../api/queries';

vi.mock('../api/queries', () => ({
  api: {
    health: vi.fn(),
    memoryHealth: vi.fn(),
  },
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <SystemPage />
    </QueryClientProvider>
  );
}

function cardStatus(name: string) {
  return screen.getByText(name).parentElement?.textContent ?? '';
}

describe('SystemPage', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('shows the database as unavailable while the backend itself is up', async () => {
    vi.mocked(api.health).mockResolvedValue({ status: 'degraded', database: 'unavailable' });
    vi.mocked(api.memoryHealth).mockResolvedValue({ status: 'ok' } as never);

    renderPage();

    expect(await screen.findByText('Unavailable')).toBeInTheDocument();
    expect(cardStatus('Backend')).toContain('Ok');
    expect(cardStatus('Database')).toContain('Unavailable');
  });

  it('shows the database as ok when the health check passes', async () => {
    vi.mocked(api.health).mockResolvedValue({ status: 'ok', database: 'ok' });
    vi.mocked(api.memoryHealth).mockResolvedValue({ status: 'ok' } as never);

    renderPage();

    await screen.findAllByText('Ok');
    expect(cardStatus('Database')).toContain('Ok');
  });

  it('says why memory is unavailable instead of "initializing" (QA-10)', async () => {
    vi.mocked(api.health).mockResolvedValue({ status: 'ok', database: 'ok' });
    vi.mocked(api.memoryHealth).mockResolvedValue({
      enabled: true,
      provider: 'qdrant',
      status: 'unavailable',
      collection: 'operational_cases',
      detail: "Operational memory can't reach its vector store right now; Ops Signals keeps retrying.",
    });

    renderPage();

    expect(await screen.findByText(/can't reach its vector store/)).toBeInTheDocument();
    expect(cardStatus('Qdrant')).toContain('Unavailable');
  });
});
