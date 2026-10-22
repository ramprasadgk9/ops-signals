import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Finding, FindingTrust } from '../types';
import { sendFindingFeedback } from './backendClient';
import { PluginFindingTrust } from './PluginFindingTrust';

vi.mock('./backendClient', () => ({ sendFindingFeedback: vi.fn() }));
const feedback = vi.mocked(sendFindingFeedback);

function trust(overrides: Partial<FindingTrust> = {}): FindingTrust {
  return {
    group: 'level_change_agree',
    tier: 'needs_attention',
    badge: 'strong',
    moved: null,
    checks: ['zscore', 'ruptures'],
    tested: { real: 0.62, checked: 40, random: 0.2, dataset: 'NAB', data_kind: 'cloud', fits_metric: true, measured_at: '2026-09' },
    service: { real: 0, answered: 0, min_answers: 5 },
    your_answer: null,
    ...overrides,
  };
}

describe('PluginFindingTrust', () => {
  beforeEach(() => {
    feedback.mockReset();
  });

  it('shows the badge, both columns and the answer buttons', () => {
    render(<PluginFindingTrust backendUrl="http://backend" findingId={42} trust={trust()} service="checkout" />);

    expect(screen.getByText('Strong evidence')).toBeInTheDocument();
    expect(screen.getByText('On your service')).toBeInTheDocument();
    expect(screen.getByText('62% were real')).toBeInTheDocument();
    expect(screen.getByText('0 of 5 answers')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Real problem' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('shows only the answer buttons for a context finding the team has not moved', () => {
    render(<PluginFindingTrust backendUrl="http://backend" findingId={42} trust={trust({ tier: 'context', badge: null })} service="checkout" />);

    expect(screen.getByText('Context only')).toBeInTheDocument();
    expect(screen.queryByText('On your service')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Not a problem' })).toBeInTheDocument();
  });

  it('saves an answer and shows the recomputed service count', async () => {
    feedback.mockResolvedValue({ id: 42, trust: trust({ your_answer: 'real_problem', service: { real: 1, answered: 1, min_answers: 5 } }) } as Finding);
    render(<PluginFindingTrust backendUrl="http://backend" findingId={42} trust={trust()} service="checkout" />);

    fireEvent.click(screen.getByRole('button', { name: 'Real problem' }));

    expect(feedback).toHaveBeenCalledWith('http://backend', 42, 'real_problem');
    expect(await screen.findByText('1 of 5 answers')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Real problem' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('says when the answer could not be saved', async () => {
    feedback.mockRejectedValue(new Error('down'));
    render(<PluginFindingTrust backendUrl="http://backend" findingId={42} trust={trust()} service="checkout" />);

    fireEvent.click(screen.getByRole('button', { name: 'Expected change' }));

    expect(await screen.findByText("Couldn't save your answer.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Expected change' })).toHaveAttribute('aria-pressed', 'false'));
  });

  it('renders nothing without trust', () => {
    const { container } = render(<PluginFindingTrust backendUrl="http://backend" findingId={42} trust={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('says who gave the answer, once the backend knows it', async () => {
    feedback.mockResolvedValue({ trust: trust({ your_answer: 'expected_change', answered_by: 'priya', answered_at: new Date().toISOString() }) } as Finding);
    render(<PluginFindingTrust backendUrl="http://backend" findingId={42} trust={trust()} service="checkout" />);
    expect(screen.queryByText(/^Answered/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Expected change' }));
    expect(await screen.findByText('Answered Expected change by priya · just now')).toBeInTheDocument();
  });
});
