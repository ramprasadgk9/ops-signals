import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { OtlpIngestionCard } from './OtlpIngestionCard';
import { api } from '../api/queries';

vi.mock('../api/queries', () => ({
  api: {
    otlpStatus: vi.fn(),
  },
}));

function renderPage(props: { showEndpoint?: boolean } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <OtlpIngestionCard {...props} />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('OtlpIngestionCard', () => {
  it('shows "no data received yet" when nothing has been pushed', async () => {
    vi.mocked(api.otlpStatus).mockResolvedValue({
      endpoint_path: '/api/otlp/v1/metrics',
      points_received_total: 0,
      points_rejected_total: {},
      backlog_size: 0,
      last_analysis_cycle_duration_seconds: 0,
      last_analysis_cycle_groups_processed: 0,
    });

    renderPage();

    expect(await screen.findByText('OTLP Metrics Ingestion')).toBeInTheDocument();
    expect(await screen.findByText('No data received yet')).toBeInTheDocument();
    expect(screen.getByText(/\/api\/otlp\/v1\/metrics/)).toBeInTheDocument();
  });

  it('shows "receiving data" and live counts once points have arrived', async () => {
    vi.mocked(api.otlpStatus).mockResolvedValue({
      endpoint_path: '/api/otlp/v1/metrics',
      points_received_total: 288,
      points_rejected_total: { cardinality_limit: 3 },
      backlog_size: 42,
      last_analysis_cycle_duration_seconds: 0.5,
      last_analysis_cycle_groups_processed: 1,
    });

    renderPage();

    expect(await screen.findByText('Receiving data')).toBeInTheDocument();
    expect(screen.getByText('288')).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
    expect(screen.getByText(/3 \(cardinality_limit\)/)).toBeInTheDocument();
  });

  it('surfaces an error state instead of crashing when the status call fails', async () => {
    vi.mocked(api.otlpStatus).mockRejectedValue(new Error('network error'));

    renderPage();

    await waitFor(() => expect(screen.getByText('Could not load OTLP ingestion status.')).toBeInTheDocument());
  });

  it('leaves the endpoint out when the page already shows it', async () => {
    vi.mocked(api.otlpStatus).mockResolvedValue({
      endpoint_path: '/api/otlp/v1/metrics',
      points_received_total: 5,
      points_rejected_total: {},
      backlog_size: 1,
      last_analysis_cycle_duration_seconds: 0,
      last_analysis_cycle_groups_processed: 0,
    });

    renderPage({ showEndpoint: false });

    expect(await screen.findByText('OTLP Ingestion Activity')).toBeInTheDocument();
    expect(await screen.findByText('Receiving data')).toBeInTheDocument();
    expect(screen.queryByText(/\/api\/otlp\/v1\/metrics/)).not.toBeInTheDocument();
  });
});
