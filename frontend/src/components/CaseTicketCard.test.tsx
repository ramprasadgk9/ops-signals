import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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

function renderCard(props: { showSetupHint?: boolean } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <CaseTicketCard caseId={7} {...props} />
    </QueryClientProvider>
  );
}

const TICKETING_OFF = { enabled: false, provider: 'jira', provider_configured: false, webhook_secret_configured: false };
const TICKETING_ON = { enabled: true, provider: 'jira', provider_configured: true, webhook_secret_configured: true };

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

describe('CaseTicketCard help', () => {
  beforeEach(() => {
    vi.mocked(api.ticketingStatus).mockReset();
    vi.mocked(api.getCaseTicket).mockReset().mockResolvedValue(null);
  });

  it('shows a one-line Jira tip instead of nothing when ticketing is off and the page asks for it', async () => {
    vi.mocked(api.ticketingStatus).mockResolvedValue(TICKETING_OFF);

    renderCard({ showSetupHint: true });

    expect(await screen.findByText('Track this case in Jira')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Watch how \(1 min\)/ })).toBeInTheDocument();
    expect(screen.queryByText('External Ticketing')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Create Jira Ticket' })).not.toBeInTheDocument();
  });

  it('opens the setup steps from the tip', async () => {
    vi.mocked(api.ticketingStatus).mockResolvedValue(TICKETING_OFF);

    renderCard({ showSetupHint: true });
    fireEvent.click(await screen.findByRole('button', { name: 'How to turn it on' }));

    expect(await screen.findByText('Turn on Jira ticketing')).toBeInTheDocument();
    expect(screen.getByText(/OPS_SIGNALS_TICKETING_ENABLED=true/)).toBeInTheDocument();
  });

  it('plays the walkthrough from the tip', async () => {
    vi.mocked(api.ticketingStatus).mockResolvedValue(TICKETING_OFF);

    renderCard({ showSetupHint: true });
    fireEvent.click(await screen.findByRole('button', { name: /Watch how \(1 min\)/ }));

    const video = await screen.findByLabelText('Jira ticketing walkthrough video');
    expect(video.getAttribute('src')).toMatch(/walkthroughs\/jira-ticketing\.webm$/);
  });

  it('cannot be dismissed, so the feature stays discoverable', async () => {
    vi.mocked(api.ticketingStatus).mockResolvedValue(TICKETING_OFF);

    renderCard({ showSetupHint: true });

    expect(await screen.findByText('Track this case in Jira')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /hide|dismiss|close/i })).not.toBeInTheDocument();
  });

  it('shows no tip where the page does not ask for it', async () => {
    vi.mocked(api.ticketingStatus).mockResolvedValue(TICKETING_OFF);

    const { container } = renderCard();

    await waitFor(() => expect(api.getCaseTicket).toHaveBeenCalledWith(7));
    expect(container).toBeEmptyDOMElement();
  });

  it('shows no tip when ticketing is on; the card has a Watch how link instead', async () => {
    vi.mocked(api.ticketingStatus).mockResolvedValue(TICKETING_ON);

    renderCard({ showSetupHint: true });

    expect(await screen.findByText('External Ticketing')).toBeInTheDocument();
    expect(screen.queryByText('Track this case in Jira')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Watch how' }));
    expect(await screen.findByLabelText('Jira ticketing walkthrough video')).toBeInTheDocument();
  });
});
