import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SlackDeliveryCard } from './SlackDeliveryCard';
import { api } from '../api/queries';

vi.mock('../api/queries', () => ({ api: { slackStatus: vi.fn() } }));

function renderCard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <SlackDeliveryCard />
    </QueryClientProvider>
  );
}

describe('SlackDeliveryCard', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('shows a message that is being retried and why', async () => {
    vi.mocked(api.slackStatus).mockResolvedValue({
      enabled: true,
      delivered_last_24h: 4,
      retrying: 1,
      failed_last_24h: 0,
      last_failure: { title: 'cpu_usage moved to a new baseline.', service: 'checkout', error: 'Slack webhook returned HTTP 500', attempts: 2, status: 'pending', created_at: '2026-10-16T22:00:00Z', next_retry_at: '2026-10-16T22:02:00Z' },
    });

    renderCard();

    expect(await screen.findByText('Retrying', { selector: '.MuiChip-label' })).toBeInTheDocument();
    expect(screen.getByText(/Retrying: cpu_usage moved to a new baseline\. \(checkout\)/)).toBeInTheDocument();
    expect(screen.getByText(/Slack webhook returned HTTP 500 · 2 attempts · next try/)).toBeInTheDocument();
  });

  it('flags messages that were never delivered', async () => {
    vi.mocked(api.slackStatus).mockResolvedValue({
      enabled: true,
      delivered_last_24h: 0,
      retrying: 0,
      failed_last_24h: 1,
      last_failure: { title: 'checkout CPU', error: 'Slack webhook unreachable', attempts: 6, status: 'failed', created_at: '2026-10-16T22:00:00Z' },
    });

    renderCard();

    expect(await screen.findByText('Messages failed')).toBeInTheDocument();
    expect(screen.getByText(/Not delivered: checkout CPU/)).toBeInTheDocument();
  });

  it('says how to turn it on when it is off', async () => {
    vi.mocked(api.slackStatus).mockResolvedValue({ enabled: false, delivered_last_24h: 0, retrying: 0, failed_last_24h: 0 });

    renderCard();

    expect(await screen.findByText(/OPS_SIGNALS_SLACK_WEBHOOK_URL/)).toBeInTheDocument();
  });
});
