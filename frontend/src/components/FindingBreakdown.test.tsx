import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { FindingBreakdown } from './FindingBreakdown';
import {
  breakdownNextStep,
  breakdownScopeLabel,
  breakdownSentence,
  findingBreakdown,
  type BreakdownPart,
  type FindingBreakdown as Breakdown,
} from '../utils/findingBreakdown';

function part(value: string, overrides: Partial<BreakdownPart> = {}): BreakdownPart {
  return { value, before: 0.2, after: 0.2, change: 0, relative_change: 0, share: 0.02, moved: false, new: false, gone: false, ...overrides };
}

const onePod: Breakdown = {
  status: 'ok',
  label: 'pod',
  mode: 'share',
  spread: 'concentrated',
  direction: 'up',
  parts_total: 6,
  parts_changed: 1,
  new_parts: 0,
  top: [
    part('checkout-x2', { before: 0.2, after: 3.57, change: 3.37, relative_change: 16.85, share: 0.91, moved: true }),
    part('checkout-a1', { share: 0.03 }),
    part('checkout-k4', { share: 0.02 }),
  ],
  others: { count: 3, moved: 0, share: 0.04 },
};

const everyPod: Breakdown = {
  ...onePod,
  spread: 'widespread',
  parts_changed: 6,
  top: ['a1', 'x2', 'k4', 'm8', 'p3'].map((name) => part(name, { share: 0.17, moved: true, relative_change: 4.5 })),
  others: { count: 1, moved: 1, share: 0.15 },
};

const newPods: Breakdown = {
  ...onePod,
  spread: 'partial',
  parts_changed: 2,
  new_parts: 2,
  top: [
    part('checkout-8c2-q1', { before: null, after: 1.5, share: 0.47, moved: true, new: true }),
    part('checkout-8c2-w7', { before: null, after: 1.4, share: 0.41, moved: true, new: true }),
    part('checkout-7f9-a1', { share: 0.03 }),
  ],
  others: null,
};

const slowPodLatency: Breakdown = {
  status: 'ok',
  label: 'pod',
  mode: 'changed_parts',
  spread: 'concentrated',
  direction: 'up',
  parts_total: 6,
  parts_changed: 1,
  top: [
    part('checkout-x2', { before: 0.12, after: 0.48, relative_change: 3.0, moved: true, share: undefined }),
    part('checkout-a1', { before: 0.12, after: 0.121, relative_change: 0.01, share: undefined }),
  ],
  others: { count: 4, moved: 0 },
};

describe('findingBreakdown', () => {
  it('returns null when the finding has no breakdown', () => {
    expect(findingBreakdown({ comparison_json: {} })).toBeNull();
    expect(findingBreakdown({ comparison_json: { breakdown: 'nonsense' } })).toBeNull();
    expect(findingBreakdown({ comparison_json: { breakdown: { status: 'weird' } } })).toBeNull();
  });

  it('reads a stored breakdown', () => {
    expect(findingBreakdown({ comparison_json: { breakdown: onePod } })).toEqual(onePod);
  });
});

describe('breakdown wording', () => {
  it('one bad pod: names it with its share', () => {
    expect(breakdownScopeLabel(onePod)).toBe('1 of 6 pods');
    expect(breakdownSentence(onePod)).toBe('91% of the increase comes from pod checkout-x2, 1 of 6 pods.');
    expect(breakdownNextStep(onePod)).toContain('rollback is probably not needed');
  });

  it('every pod: says it is not one instance', () => {
    expect(breakdownScopeLabel(everyPod)).toBe('6 of 6 pods');
    expect(breakdownSentence(everyPod)).toBe('All 6 pods rose by a similar amount.');
    expect(breakdownNextStep(everyPod)).toContain('Not a single bad pod');
  });

  it('new pods: points at a rollout', () => {
    expect(breakdownScopeLabel(newPods)).toBe('2 new pods');
    expect(breakdownSentence(newPods)).toBe('88% of the increase comes from 2 of 6 pods: checkout-8c2-q1, checkout-8c2-w7.');
    expect(breakdownNextStep(newPods)).toContain('rollout in progress');
  });

  it('latency: no percentage shares, before and after instead', () => {
    expect(breakdownSentence(slowPodLatency)).toBe('Only pod checkout-x2 rose (0.12 → 0.48). The other 5 pods are unchanged.');
  });

  it('no scope label for a skipped breakdown', () => {
    expect(breakdownScopeLabel({ status: 'skipped', reason: 'single_part' })).toBeNull();
  });
});

describe('FindingBreakdown component', () => {
  it('renders the sentence, bars and next step', () => {
    render(<FindingBreakdown breakdown={onePod} />);

    expect(screen.getByText('Where the change came from')).toBeInTheDocument();
    expect(screen.getByText('1 of 6 pods')).toBeInTheDocument();
    expect(screen.getByText('91%')).toBeInTheDocument();
    expect(screen.getByText('+ 3 other pods, unchanged')).toBeInTheDocument();
    expect(screen.getByText(/Likely next step:/)).toBeInTheDocument();
  });

  it('marks new pods', () => {
    render(<FindingBreakdown breakdown={newPods} />);

    expect(screen.getByText('checkout-8c2-q1 ✦')).toBeInTheDocument();
    expect(screen.getByText(/new pod: no data before the change/)).toBeInTheDocument();
  });

  it('explains why a breakdown is unavailable', () => {
    render(<FindingBreakdown breakdown={{ status: 'skipped', reason: 'query_shape_not_supported' }} />);

    expect(screen.getByText(/can’t be split by pod automatically/)).toBeInTheDocument();
  });
});
