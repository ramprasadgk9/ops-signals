import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { ShiftHandoffButton } from './ShiftHandoffButton';
import { api } from '../api/queries';
import type { AIStatus, ShiftHandoff } from '../types';

const aiStatus: AIStatus = { enabled: true, provider: 'ollama', model: 'test-model', endpoint: null, api_key_set: null, active: true, issue: null };

vi.mock('../api/queries', () => ({
  api: {
    shiftHandoff: vi.fn(),
    shiftHandoffNote: vi.fn(),
    aiStatus: vi.fn(),
  },
}));

const handoff: ShiftHandoff = {
  generated_at: '2026-10-27T12:00:00Z',
  hours: 12,
  since: '2026-10-27T00:00:00Z',
  new_findings: 4,
  cases_opened: 2,
  cases_resolved: 1,
  cases_still_open: 2,
  older_open_cases: 0,
  watch: [
    { kind: 'case', title: 'Payments errors up', severity: 'critical', service: 'payments', metric_name: 'error_rate', case_id: 10, finding_id: 1, deploy_version: 'v2.3', reason: 'open 8 hours, started after deploy v2.3, critical', live: true },
    { kind: 'finding', title: 'Search slower', severity: 'high', service: 'search', metric_name: 'latency_p95', finding_id: 4, reason: 'no case yet, seen 3 hours ago, high', live: true },
  ],
  summary: 'Last 12 hours: 4 new findings, 2 cases opened, 1 resolved. 2 cases still open. Watch first: case #10 (payments error_rate), open 8 hours, started after deploy v2.3, critical.',
};

function renderCard(open = true) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ShiftHandoffButton />
      </MemoryRouter>
    </QueryClientProvider>
  );
  if (open) fireEvent.click(screen.getByRole('button', { name: 'Shift handoff' }));
  return view;
}

describe('ShiftHandoffButton', () => {
  beforeEach(() => {
    vi.mocked(api.shiftHandoff).mockReset().mockResolvedValue(handoff);
    vi.mocked(api.shiftHandoffNote).mockReset();
    vi.mocked(api.aiStatus).mockReset().mockResolvedValue({ ...aiStatus, enabled: false, provider: 'none', active: false });
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
  });

  it('shows the counts and what to watch first, linked to the case', async () => {
    renderCard();
    expect(await screen.findByTestId('shift-handoff-counts')).toHaveTextContent('4 new findings · 2 cases opened · 1 resolved · 2 still open');
    const watch = screen.getByTestId('shift-handoff-watch');
    expect(watch).toHaveTextContent('Case #10 · payments / error_rate');
    expect(watch).toHaveTextContent('started after deploy v2.3');
    expect(screen.getByRole('link', { name: 'Open case' })).toHaveAttribute('href', '/cases/10');
    expect(screen.getByRole('link', { name: /search \/ latency_p95/ })).toHaveAttribute('href', '/findings?window=24h&finding=4');
    expect(api.shiftHandoff).toHaveBeenCalledWith(12);
  });

  it('copies the plain summary and the list, and has no AI button with AI off', async () => {
    renderCard();
    await screen.findByTestId('shift-handoff-counts');
    fireEvent.click(screen.getByRole('button', { name: 'Copy for Slack' }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalled());
    const text = vi.mocked(navigator.clipboard.writeText).mock.calls[0][0];
    expect(text.startsWith(handoff.summary)).toBe(true);
    expect(text).toContain('- Case #10 · payments / error_rate: open 8 hours, started after deploy v2.3, critical http://localhost:3000/cases/10');
    expect(await screen.findByRole('status')).toHaveTextContent('Copied');
    expect(screen.queryByRole('button', { name: 'Write with AI' })).toBeNull();
  });

  it('switches the window', async () => {
    renderCard();
    fireEvent.click(await screen.findByRole('button', { name: 'Last 24h' }));
    await waitFor(() => expect(api.shiftHandoff).toHaveBeenCalledWith(24));
  });

  it('writes the note with AI on and copies it instead of the plain summary', async () => {
    vi.mocked(api.aiStatus).mockResolvedValue(aiStatus);
    vi.mocked(api.shiftHandoffNote).mockResolvedValue({ available: true, note: 'Quiet shift except payments: watch case #10.' });
    renderCard();
    fireEvent.click(await screen.findByRole('button', { name: 'Write with AI' }));
    expect(await screen.findByTestId('shift-handoff-note')).toHaveTextContent('Quiet shift except payments: watch case #10.');
    fireEvent.click(screen.getByRole('button', { name: 'Copy for Slack' }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalled());
    expect(vi.mocked(navigator.clipboard.writeText).mock.calls[0][0].startsWith('Quiet shift except payments: watch case #10.')).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Show plain summary' }));
    expect(screen.queryByTestId('shift-handoff-note')).toBeNull();
  });

  it('says when the AI note could not be written', async () => {
    vi.mocked(api.aiStatus).mockResolvedValue(aiStatus);
    vi.mocked(api.shiftHandoffNote).mockResolvedValue({ available: false, reason_code: 'failed' });
    renderCard();
    fireEvent.click(await screen.findByRole('button', { name: 'Write with AI' }));
    expect(await screen.findByText(/couldn't be written/)).toBeInTheDocument();
  });

  it('loads nothing until the button is pressed, and says so when the handoff cannot be read', async () => {
    renderCard(false);
    expect(api.shiftHandoff).not.toHaveBeenCalled();
    vi.mocked(api.shiftHandoff).mockRejectedValue(new Error('down'));
    fireEvent.click(screen.getByRole('button', { name: 'Shift handoff' }));
    expect(await screen.findByText(/could not be loaded/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy for Slack' })).toBeDisabled();
  });

  it('closes when a watch item is opened', async () => {
    renderCard();
    fireEvent.click(await screen.findByRole('link', { name: 'Open case' }));
    await waitFor(() => expect(screen.queryByTestId('shift-handoff')).toBeNull());
  });
});
