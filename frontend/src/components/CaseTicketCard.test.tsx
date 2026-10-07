import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/queries';
import { CaseTicketCard } from './CaseTicketCard';

vi.mock('../api/queries', () => ({
  api: {
    ticketingStatus: vi.fn(),
    getCaseTicket: vi.fn(),
    getCaseTicketEvents: vi.fn().mockResolvedValue([]),
    getCase: vi.fn().mockResolvedValue({ id: 7, outcome_status: 'pending' }),
    getTicketingWebhookInfo: vi.fn(),
  },
}));

function renderCard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <CaseTicketCard caseId={7} />
    </QueryClientProvider>
  );
}

describe('CaseTicketCard visibility', () => {
  beforeEach(() => {
    vi.mocked(api.ticketingStatus).mockReset();
    vi.mocked(api.getCaseTicket).mockReset();
  });

  it('renders nothing on a case when ticketing is off and no ticket is linked', async () => {
    vi.mocked(api.ticketingStatus).mockResolvedValue({ enabled: false, provider: 'jira', provider_configured: false, webhook_secret_configured: false });
    vi.mocked(api.getCaseTicket).mockResolvedValue(null);

    const { container } = renderCard();

    await waitFor(() => expect(api.ticketingStatus).toHaveBeenCalled());
    await waitFor(() => expect(api.getCaseTicket).toHaveBeenCalledWith(7));
    expect(screen.queryByText('External Ticketing')).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the card when ticketing is on', async () => {
    vi.mocked(api.ticketingStatus).mockResolvedValue({ enabled: true, provider: 'jira', provider_configured: true, webhook_secret_configured: true });
    vi.mocked(api.getCaseTicket).mockResolvedValue(null);

    renderCard();

    expect(await screen.findByText('External Ticketing')).toBeInTheDocument();
  });
});
