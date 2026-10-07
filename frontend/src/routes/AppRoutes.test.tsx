import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { AppShell } from '../components/AppShell';
import { AppRoutes } from './AppRoutes';

// Every api call resolves empty; these tests only check routing and the sidebar.
vi.mock('../api/queries', () => ({
  api: new Proxy({}, { get: () => vi.fn().mockResolvedValue([]) }),
}));

function renderRoute(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <AppShell>
          <AppRoutes />
        </AppShell>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('removed Experiments page', () => {
  it('sends old /experiments links to the Ruptures Change Point Lab', async () => {
    renderRoute('/experiments');

    expect(await screen.findByText('Ruptures Change Point Lab', { selector: 'h1, h2, h3, h4, h5, h6' })).toBeInTheDocument();
    expect(screen.queryByText('Analyzer Experiment Dashboard')).not.toBeInTheDocument();
  });

  it('is gone from the sidebar, while the Analyzer Workbench stays', async () => {
    renderRoute('/');

    expect(await screen.findByText('Analyzer Workbench')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Experiments' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Experiments' })).not.toBeInTheDocument();
    expect(screen.queryByText('Experiments', { exact: true })).not.toBeInTheDocument();
  });
});
