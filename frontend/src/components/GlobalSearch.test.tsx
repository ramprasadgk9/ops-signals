import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { GlobalSearch } from './GlobalSearch';
import { api } from '../api/queries';
import type { Finding } from '../types';

vi.mock('../api/queries', () => ({
  api: {
    findingsSearch: vi.fn(),
  },
}));

function CurrentPath() {
  return <div data-testid="current-path">{useLocation().pathname}</div>;
}

function renderSearch() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/overview']}>
        <GlobalSearch />
        <Routes>
          <Route path="*" element={<CurrentPath />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const otlpFinding: Finding = {
  id: 41,
  service: 'test-otlp-service',
  metric_name: 'cpu_usage',
  title: 'cpu_usage is trending in one direction.',
  summary: 'trend',
  category: 'behavior_change',
  health_status: 'significant',
  importance_score: 0.78,
  investigation_priority: 2,
  signal_ids: [],
  comparison_json: {},
  created_at: '2026-09-22T16:24:25Z',
};

describe('GlobalSearch', () => {
  it('does not search before the minimum query length is reached', () => {
    vi.mocked(api.findingsSearch).mockResolvedValue([]);
    renderSearch();

    const input = screen.getByPlaceholderText('Search findings, cases, metrics, services...');
    fireEvent.change(input, { target: { value: 'o' } });

    expect(api.findingsSearch).not.toHaveBeenCalled();
  });

  it('searches across a 7-day window and shows matching results in a dropdown', async () => {
    vi.mocked(api.findingsSearch).mockResolvedValue([otlpFinding]);
    renderSearch();

    const input = screen.getByPlaceholderText('Search findings, cases, metrics, services...');
    fireEvent.change(input, { target: { value: 'otlp' } });

    expect(await screen.findByText('test-otlp-service / cpu_usage')).toBeInTheDocument();
    expect(api.findingsSearch).toHaveBeenCalledWith({ q: 'otlp', window: '7d', limit: 8 });
  });

  it('navigates to the Findings page when a result is selected', async () => {
    vi.mocked(api.findingsSearch).mockResolvedValue([otlpFinding]);
    renderSearch();

    const input = screen.getByPlaceholderText('Search findings, cases, metrics, services...');
    fireEvent.change(input, { target: { value: 'otlp' } });

    const option = await screen.findByText('test-otlp-service / cpu_usage');
    fireEvent.click(option);

    expect(await screen.findByTestId('current-path')).toHaveTextContent('/findings');
  });
});
