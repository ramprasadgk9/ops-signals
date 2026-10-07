import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { CoveragePanel } from './CoveragePanel';
import { api } from '../api/queries';
import type { CoverageReport } from '../types';

vi.mock('../api/queries', () => ({ api: { monitoringCoverage: vi.fn() } }));

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><CoveragePanel /></MemoryRouter>
    </QueryClientProvider>
  );
}

const incident = (overrides: Partial<CoverageReport['incidents'][number]>): CoverageReport['incidents'][number] => ({
  case_id: 1, title: 'Incident', service: 'checkout-api', started_at: '2026-09-01T10:00:00Z', status: 'missed', label: 'Missed',
  explanation: 'checkout-api was analysed while this happened, and nothing was flagged.', evidence: [], seen_elsewhere: 0, ...overrides,
});

const report = (overrides: Partial<CoverageReport> = {}): CoverageReport => ({
  available: true,
  window_days: 365,
  incidents_considered: 4,
  counts: { missed: 1, not_watched: 1, flagged_other: 1, unknown: 0, detected: 1 },
  services: [
    { service: 'checkout-api', counts: { detected: 1, flagged_other: 1, missed: 1 } },
    { service: 'inventory-svc', counts: { not_watched: 1 } },
  ],
  incidents: [
    incident({ case_id: 5, title: 'Login failures', service: 'auth-svc', seen_elsewhere: 1, seen_elsewhere_case_id: 12,
      explanation: 'auth-svc was analysed and nothing was flagged. A similar problem was detected 1 other time.' }),
    incident({ case_id: 6, title: 'Inventory disk full', service: 'inventory-svc', status: 'not_watched', label: 'Not watched', explanation: 'Nothing analysed inventory-svc.' }),
    incident({ case_id: 7, title: 'Checkout slow', status: 'flagged_other', label: 'Flagged something else', explanation: '1 thing was flagged.',
      evidence: [{ kind: 'finding', id: 3, title: 'memory has unusual activity', similarity: 0.52 }] }),
    incident({ case_id: 8, title: 'Checkout CPU pinned', status: 'detected', label: 'Detected', explanation: 'Flagged while it happened.' }),
  ],
  ...overrides,
});

describe('CoveragePanel', () => {
  afterEach(() => vi.mocked(api.monitoringCoverage).mockReset());

  it('counts what monitoring did and lists the gaps first, with what to do', async () => {
    vi.mocked(api.monitoringCoverage).mockResolvedValue(report());
    renderPanel();

    const tiles = await screen.findByTestId('coverage-tiles');
    expect(within(tiles).getByText('Missed')).toBeInTheDocument();
    expect(within(tiles).getByText('Not watched')).toBeInTheDocument();
    const rows = screen.getAllByTestId('coverage-incident');
    expect(rows.map((row) => within(row).getByRole('link', { name: /Login|Inventory|Checkout/ }).textContent)).toEqual([
      'Login failures', 'Inventory disk full', 'Checkout slow',
    ]);
    expect(screen.getByText(/memory has unusual activity \(52%\)/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open the latest detected case like it' })).toHaveAttribute('href', '/cases/12');
    expect(screen.queryByText('Checkout CPU pinned')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Show 1 detected incident' }));
    expect(screen.getByRole('link', { name: 'Checkout CPU pinned' })).toHaveAttribute('href', '/cases/8');
  });

  it('draws a bar per service with each status named', async () => {
    vi.mocked(api.monitoringCoverage).mockResolvedValue(report());
    renderPanel();

    const bars = await screen.findByTestId('coverage-by-service');
    expect(within(bars).getByRole('img', { name: 'checkout-api: 1 missed' })).toBeInTheDocument();
    expect(within(bars).getByRole('img', { name: 'inventory-svc: 1 not watched' })).toBeInTheDocument();
  });

  it('skips the per-service bars for a single service', async () => {
    vi.mocked(api.monitoringCoverage).mockResolvedValue(report({ services: [{ service: 'checkout-api', counts: { missed: 2 } }] }));
    renderPanel();

    await screen.findByTestId('coverage-tiles');
    expect(screen.queryByTestId('coverage-by-service')).not.toBeInTheDocument();
  });

  it('tells you to import postmortems when there are none', async () => {
    vi.mocked(api.monitoringCoverage).mockResolvedValue(report({ incidents: [], incidents_considered: 0, reason: 'No past incidents imported in this window.' }));
    renderPanel();

    expect(await screen.findByText('No past incidents imported in this window.')).toBeInTheDocument();
  });

  it('asks for the chosen window', async () => {
    vi.mocked(api.monitoringCoverage).mockResolvedValue(report());
    renderPanel();

    fireEvent.click(await screen.findByText('All'));
    await vi.waitFor(() => expect(api.monitoringCoverage).toHaveBeenLastCalledWith(3650));
  });
});
