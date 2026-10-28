import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { PastCaseMatch, SeenBeforeResponse } from '../types';
import { getFindingSeenBefore } from './backendClient';
import { PluginSeenBefore } from './PluginSeenBefore';

vi.mock('./backendClient', () => ({ getFindingSeenBefore: vi.fn(), getAiStatus: vi.fn(async () => ({ active: false })), getFixCameBackWhy: vi.fn() }));
const seenBefore = vi.mocked(getFindingSeenBefore);

function match(overrides: Partial<PastCaseMatch>): PastCaseMatch {
  return { case_id: 1, title: 'Case', similarity_score: 0.9, strength: 'strong', same_service: true, service: 'checkout', metric_name: 'cpu_usage', ...overrides };
}

function response(overrides: Partial<SeenBeforeResponse>): SeenBeforeResponse {
  return { finding_id: 42, available: true, service: 'checkout', matches: [], novelty: null, ...overrides };
}

describe('PluginSeenBefore', () => {
  beforeEach(() => {
    seenBefore.mockReset();
  });

  it('warns first when the finding is back soon after a fix, without an AI button when AI is off', async () => {
    seenBefore.mockResolvedValue(response({
      came_back: { case_id: 3, title: 'Checkout CPU after deploy', fixed_at: '2026-10-24T15:10:00', days: 0, fix: 'Rolled back to v2.2' },
      matches: [match({ case_id: 3, title: 'Checkout CPU after deploy' })],
    }));

    render(<PluginSeenBefore backendUrl="http://backend" findingId={42} service="checkout" />);

    const banner = await screen.findByTestId('plugin-fix-came-back');
    expect(banner).toHaveTextContent('This came back less than a day after it was fixed.');
    expect(banner).toHaveTextContent('Case #3 Checkout CPU after deploy was resolved on');
    expect(screen.queryByRole('button', { name: /Why might it not have held/ })).not.toBeInTheDocument();
  });

  it('lists same-service matches first with cause, fix and score, and folds other services away', async () => {
    seenBefore.mockResolvedValue(response({
      novelty: { level: 'recurring', label: 'Recurring · 2 past cases', explanation: 'Happened twice on checkout this month.', matching_cases: 2, all_matching_cases: 3 },
      matches: [
        match({ case_id: 7, title: 'Payments CPU saturation', service: 'payments', same_service: false, similarity_score: 0.81 }),
        match({ case_id: 3, title: 'Checkout CPU after deploy', root_cause_summary: 'Bad cache config in v2.3', corrective_action: 'Rolled back to v2.2', similarity_score: 0.92 }),
        match({ case_id: 4, title: 'Checkout CPU drift', strength: 'possible', similarity_score: 0.71 }),
      ],
    }));

    render(<PluginSeenBefore backendUrl="http://backend" findingId={42} service="checkout" />);

    expect(await screen.findByText('Recurring · 2 past cases')).toBeInTheDocument();
    expect(seenBefore).toHaveBeenCalledWith('http://backend', 42);
    expect(screen.getByText('Happened twice on checkout this month.')).toBeInTheDocument();
    const rows = screen.getAllByTestId('plugin-past-case-match');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('Checkout CPU after deploy');
    expect(rows[0]).toHaveTextContent('Strong match · 92%');
    expect(rows[0]).toHaveTextContent('Cause: Bad cache config in v2.3');
    expect(rows[0]).toHaveTextContent('Fix: Rolled back to v2.2');
    expect(rows[1]).toHaveTextContent('Possible match · 71%');
    expect(screen.queryByText('Payments CPU saturation')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('Show 1 match on other services'));
    expect(screen.getByText('Payments CPU saturation')).toBeInTheDocument();
  });

  it('expands near-copies folded under a match', async () => {
    seenBefore.mockResolvedValue(response({
      matches: [match({ case_id: 3, title: 'Checkout CPU after deploy', more_like_this: [match({ case_id: 9, title: 'Checkout CPU again', similarity_score: 0.88 })] })],
    }));

    render(<PluginSeenBefore backendUrl="http://backend" findingId={42} service="checkout" />);

    fireEvent.click(await screen.findByText('+1 more like this'));
    expect(screen.getByText('Checkout CPU again')).toBeInTheDocument();
  });

  it('says so when memory has nothing like it yet', async () => {
    seenBefore.mockResolvedValue(response({ matches: [] }));

    render(<PluginSeenBefore backendUrl="http://backend" findingId={42} service="checkout" />);

    expect(await screen.findByText(/Nothing like this in memory yet/)).toBeInTheDocument();
  });

  it('shows the backend reason when memory is unavailable', async () => {
    seenBefore.mockResolvedValue(response({ available: false, reason: 'Past cases could not be searched right now.' }));

    render(<PluginSeenBefore backendUrl="http://backend" findingId={42} />);

    expect(await screen.findByText('Past cases could not be searched right now.')).toBeInTheDocument();
  });

  it('shows an error when the request fails', async () => {
    seenBefore.mockRejectedValue(new Error('network'));

    render(<PluginSeenBefore backendUrl="http://backend" findingId={42} />);

    expect(await screen.findByText(/Past cases could not be searched. Check the backend connection./)).toBeInTheDocument();
  });

  it('renders nothing for a finding that was never persisted', () => {
    const { container } = render(<PluginSeenBefore backendUrl="http://backend" findingId={0} />);

    expect(container).toBeEmptyDOMElement();
    expect(seenBefore).not.toHaveBeenCalled();
  });
});
