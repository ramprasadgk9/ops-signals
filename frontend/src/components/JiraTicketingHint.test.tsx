import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/queries';
import { JiraTicketingHint } from './JiraTicketingHint';

vi.mock('../api/queries', () => ({
  api: { ticketingStatus: vi.fn() },
}));

const TICKETING_OFF = { enabled: false, provider: 'jira', provider_configured: false, webhook_secret_configured: false };
const TICKETING_ON = { enabled: true, provider: 'jira', provider_configured: true, webhook_secret_configured: true };

function renderHint(props: { subject?: 'cases' | 'case' } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <JiraTicketingHint {...props} />
    </QueryClientProvider>
  );
}

describe('JiraTicketingHint', () => {
  beforeEach(() => {
    vi.mocked(api.ticketingStatus).mockReset();
  });

  it('shows a banner with the video and the setup steps while ticketing is off', async () => {
    vi.mocked(api.ticketingStatus).mockResolvedValue(TICKETING_OFF);

    renderHint({ subject: 'case' });

    expect(await screen.findByText('Track this case in Jira')).toBeInTheDocument();
    expect(screen.getByText(/Jira ticketing is off on this server/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Watch how \(1 min\)/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'How to turn it on' })).toBeInTheDocument();
  });

  it('cannot be dismissed, so the feature stays discoverable', async () => {
    vi.mocked(api.ticketingStatus).mockResolvedValue(TICKETING_OFF);

    renderHint();

    expect(await screen.findByText('Track cases in Jira')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /hide|dismiss|close/i })).not.toBeInTheDocument();
  });

  it('plays the walkthrough', async () => {
    vi.mocked(api.ticketingStatus).mockResolvedValue(TICKETING_OFF);

    renderHint();
    fireEvent.click(await screen.findByRole('button', { name: /Watch how \(1 min\)/ }));

    const video = await screen.findByLabelText('Jira ticketing walkthrough video');
    expect(video.getAttribute('src')).toMatch(/walkthroughs\/jira-ticketing\.webm$/);
  });

  it('opens the setup steps', async () => {
    vi.mocked(api.ticketingStatus).mockResolvedValue(TICKETING_OFF);

    renderHint();
    fireEvent.click(await screen.findByRole('button', { name: 'How to turn it on' }));

    expect(await screen.findByText('Turn on Jira ticketing')).toBeInTheDocument();
    expect(screen.getByText(/OPS_SIGNALS_TICKETING_ENABLED=true/)).toBeInTheDocument();
  });

  it('says how to restart the backend for each way of running Ops Signals', async () => {
    vi.mocked(api.ticketingStatus).mockResolvedValue(TICKETING_OFF);

    renderHint();
    fireEvent.click(await screen.findByRole('button', { name: 'How to turn it on' }));

    expect(await screen.findByText('./scripts/run_all.sh')).toBeInTheDocument();
    expect(screen.getByText('docker compose -f docker-compose.packaged.yml up -d backend')).toBeInTheDocument();
    expect(screen.getByText(/kubectl rollout restart deployment -l app.kubernetes.io\/instance=<release>,app.kubernetes.io\/component=backend/)).toBeInTheDocument();
  });

  it('shows nothing once ticketing is on (the case card takes over)', async () => {
    vi.mocked(api.ticketingStatus).mockResolvedValue(TICKETING_ON);

    const { container } = renderHint();

    await waitFor(() => expect(api.ticketingStatus).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('shows nothing when the status cannot be read (an older backend)', async () => {
    vi.mocked(api.ticketingStatus).mockRejectedValue(new Error('404'));

    const { container } = renderHint();

    await waitFor(() => expect(api.ticketingStatus).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
