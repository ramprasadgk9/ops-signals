import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PluginBreakdownDisclosure, PluginBreakdownSection, PluginScopeChip } from './PluginBreakdown';
import type { FindingBreakdown } from '../utils/findingBreakdown';

const onePod: FindingBreakdown = {
  status: 'ok',
  label: 'pod',
  mode: 'share',
  spread: 'concentrated',
  direction: 'up',
  parts_total: 6,
  parts_changed: 1,
  top: [
    { value: 'checkout-x2', before: 0.18, after: 3.49, change: 3.31, relative_change: 18.5, share: 0.99, moved: true, new: false, gone: false },
    { value: 'checkout-a1', before: 0.2, after: 0.21, change: 0.01, relative_change: 0.05, share: 0.01, moved: false, new: false, gone: false },
  ],
  others: { count: 4, moved: 0, share: 0 },
};

const slowLatency: FindingBreakdown = {
  status: 'ok',
  label: 'pod',
  mode: 'changed_parts',
  spread: 'widespread',
  direction: 'up',
  parts_total: 2,
  parts_changed: 2,
  top: [
    { value: 'payments-a1', before: 0.1, after: 0.25, change: 0.15, relative_change: 1.5, moved: true, new: false, gone: false },
    { value: 'payments-b2', before: 0.14, after: 0.35, change: 0.21, relative_change: 1.5, moved: true, new: false, gone: false },
  ],
  others: null,
};

describe('PluginBreakdownSection', () => {
  it('shows the sentence, per-pod shares and next step', () => {
    render(<PluginBreakdownSection breakdown={onePod} />);

    expect(screen.getByText('Where the change came from')).toBeInTheDocument();
    expect(screen.getByText('99% of the increase comes from pod checkout-x2, 1 of 6 pods.')).toBeInTheDocument();
    expect(screen.getByText('99%')).toBeInTheDocument();
    expect(screen.getByText('+ 4 other pods, unchanged')).toBeInTheDocument();
    expect(screen.getByText(/rollback is probably not needed/)).toBeInTheDocument();
  });

  it('shows change against each pod’s own level for latency, not shares', () => {
    render(<PluginBreakdownSection breakdown={slowLatency} />);

    expect(screen.getByText('All 2 pods rose by a similar amount.')).toBeInTheDocument();
    expect(screen.getAllByText('+150%')).toHaveLength(2);
    expect(screen.getByText(/compared with each pod’s own normal level/)).toBeInTheDocument();
  });

  it('explains why a breakdown is unavailable', () => {
    render(<PluginBreakdownSection breakdown={{ status: 'skipped', reason: 'single_part' }} />);

    expect(screen.getByText(/only one pod or instance reports this metric/)).toBeInTheDocument();
  });
});

describe('PluginScopeChip', () => {
  it('renders the scope and opens details on click', () => {
    const onClick = vi.fn();
    render(<PluginScopeChip finding={{ comparison_json: { breakdown: onePod } }} onClick={onClick} />);

    const chip = screen.getByRole('button', { name: '1 of 6 pods' });
    expect(chip).toHaveAttribute('title', '99% of the increase comes from pod checkout-x2, 1 of 6 pods. Click for the full breakdown.');
    fireEvent.click(chip);
    expect(onClick).toHaveBeenCalled();
  });

  it('renders nothing without a usable breakdown', () => {
    const { container } = render(<PluginScopeChip finding={{ comparison_json: { breakdown: { status: 'skipped', reason: 'no_data' } } }} />);

    expect(container).toBeEmptyDOMElement();
  });
});

describe('PluginBreakdownDisclosure', () => {
  it('shows and hides the breakdown when the chip is clicked', () => {
    render(<PluginBreakdownDisclosure finding={{ comparison_json: { breakdown: onePod } }} />);

    const chip = screen.getByRole('button', { name: /1 of 6 pods/ });
    expect(chip).toHaveAttribute('aria-expanded', 'false');
    expect(chip).toHaveAttribute('title', expect.stringContaining('Click to show the breakdown.'));
    expect(screen.queryByText('Where the change came from')).not.toBeInTheDocument();

    fireEvent.click(chip);
    expect(chip).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Where the change came from')).toBeInTheDocument();
    expect(screen.getByText(/rollback is probably not needed/)).toBeInTheDocument();

    fireEvent.click(chip);
    expect(screen.queryByText('Where the change came from')).not.toBeInTheDocument();
  });

  it('renders nothing for a finding without a breakdown', () => {
    const { container } = render(<PluginBreakdownDisclosure finding={{ comparison_json: {} }} />);

    expect(container).toBeEmptyDOMElement();
  });
});
