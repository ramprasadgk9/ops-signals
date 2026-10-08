import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { MetricUsageStrip } from './MetricUsageStrip';
import { api } from '../api/queries';
import type { MetricUsageResponse } from '../types';

vi.mock('../api/queries', () => ({ api: { metricUsage: vi.fn() } }));

function renderStrip() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><MetricUsageStrip /></MemoryRouter>
    </QueryClientProvider>
  );
}

const response = (blindSpots: number, names: string[]): MetricUsageResponse => ({
  enabled: true, interval_hours: 6, grafana_configured: true, last_failure: null, items_total: blindSpots, cost: null,
  snapshot: {
    id: 's', trigger: 'schedule', status: 'completed', created_at: '2026-10-07T12:00:00Z', duration_ms: 60, error: null,
    metrics_total: 299, watched: 8, blind_spots: blindSpots, unwatched: 284, missing: 0, watched_percent: 2.7, series_total: null, series_unwatched: null, sources: {},
  },
  items: names.map((metric) => ({
    metric, status: 'blind_spot', connections: ['default'], usages: [], via_recording_rules: [], problem_findings: 1, latest_finding_id: 1, analyzed: true, series: null,
  })),
});

describe('MetricUsageStrip', () => {
  afterEach(() => vi.mocked(api.metricUsage).mockReset());

  it('names the first blind spots and links to the page', async () => {
    vi.mocked(api.metricUsage).mockResolvedValue(response(7, ['demo_request_latency_ms', 'demo_queue_latency_ms', 'process_cpu_seconds_total']));
    renderStrip();

    const strip = await screen.findByTestId('metric-usage-strip');
    expect(strip).toHaveTextContent('7 metrics had problems that no dashboard or alert shows');
    expect(strip).toHaveTextContent('demo_request_latency_ms, demo_queue_latency_ms, process_cpu_seconds_total and 4 more · 8 of 299 metrics are watched');
    expect(screen.getByRole('link', { name: /Open Metric Usage/ })).toHaveAttribute('href', '/metric-usage');
    expect(api.metricUsage).toHaveBeenCalledWith(['blind_spot'], 3);
  });

  it('shows nothing without blind spots, or before the first check', async () => {
    vi.mocked(api.metricUsage).mockResolvedValue(response(0, []));
    const { container } = renderStrip();
    await waitFor(() => expect(api.metricUsage).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
