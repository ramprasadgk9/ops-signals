import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/queries';
import type { Me } from '../hooks/useWebPermissions';
import { SetupBanner } from './SetupBanner';

vi.mock('../api/queries', () => ({ api: { me: vi.fn(), setupSummary: vi.fn(), setupCheck: vi.fn() } }));

const BROKEN = {
  generated_at: '2026-10-26T00:00:00Z',
  version: 'test',
  checks: [
    { id: 'backend', group: 'required', status: 'ok', title: 'Backend', detail: '' },
    { id: 'database', group: 'required', status: 'fail', title: 'Database', detail: '' },
  ],
};
const PAGES: Me['pages'] = { '/': 'Viewer', '/setup-check': 'Admin' };
const EDITOR: Me = { signed_in: true, name: 'priya@example.com', role: 'Editor', via: 'proxy', groups: [], granted_by: null, mode: 'proxy-headers', problem: null, pages: PAGES };

function renderBanner(me: Me) {
  vi.mocked(api.me).mockResolvedValue(me);
  vi.mocked(api.setupSummary).mockResolvedValue(BROKEN as never);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter><SetupBanner /></MemoryRouter>
    </QueryClientProvider>
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('SetupBanner', () => {
  it('reads the summary, and tells someone who cannot open Setup check whom it is for', async () => {
    renderBanner(EDITOR);
    expect(await screen.findByText('Setup: 1 of 2 done. Needs fixing: Database.')).toBeInTheDocument();
    expect(await screen.findByText('Your Ops Signals admin can fix this on Setup check.')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Open Setup check' })).not.toBeInTheDocument();
    expect(api.setupCheck).not.toHaveBeenCalled();
  });

  it('links Admins to Setup check', async () => {
    renderBanner({ ...EDITOR, role: 'Admin' });
    expect(await screen.findByRole('link', { name: 'Open Setup check' })).toHaveAttribute('href', '/setup-check');
  });
});
