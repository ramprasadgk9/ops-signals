import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PastCaseMatches, rankPastMatches } from './PastCaseMatches';
import type { PastCaseMatch } from '../types';

const match = (overrides: Partial<PastCaseMatch>): PastCaseMatch => ({
  case_id: 1, title: 'A', similarity_score: 0.5, strength: 'possible', same_service: true, ...overrides,
});

describe('rankPastMatches', () => {
  it('puts same service first, then strong before possible, then score', () => {
    const ranked = rankPastMatches([
      match({ case_id: 1, same_service: false, strength: 'strong', similarity_score: 0.9 }),
      match({ case_id: 2, strength: 'possible', similarity_score: 0.6 }),
      match({ case_id: 3, strength: 'strong', similarity_score: 0.72 }),
      match({ case_id: 4, strength: 'possible', similarity_score: 0.45 }),
    ]);
    expect(ranked.map((item) => item.case_id)).toEqual([3, 2, 4, 1]);
  });
});

describe('PastCaseMatches', () => {
  it('folds matches on other services away until asked', () => {
    render(
      <PastCaseMatches
        service="checkout"
        emptyText="none"
        matches={[match({ case_id: 1, title: 'Checkout CPU', strength: 'strong', similarity_score: 0.75 }), match({ case_id: 2, title: 'Payments CPU', same_service: false })]}
      />
    );

    expect(screen.getByText('On checkout')).toBeInTheDocument();
    expect(screen.getByText('Strong match · 75%')).toBeInTheDocument();
    expect(screen.queryByText('Payments CPU')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Show 1 match on other services' }));
    expect(screen.getByText('Payments CPU')).toBeInTheDocument();
  });

  it('says so when only other services matched', () => {
    render(<PastCaseMatches service="checkout" emptyText="none" matches={[match({ same_service: false })]} />);
    expect(screen.getByText('No past cases on checkout.')).toBeInTheDocument();
  });

  it('shows the empty text when nothing matched', () => {
    render(<PastCaseMatches service="checkout" emptyText="Nothing like this yet." matches={[]} />);
    expect(screen.getByText('Nothing like this yet.')).toBeInTheDocument();
  });
});
