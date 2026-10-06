import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PastCaseMatches, rankPastMatches } from './PastCaseMatches';
import type { PastCaseMatch } from '../types';

const match = (overrides: Partial<PastCaseMatch>): PastCaseMatch => ({
  case_id: 1, title: 'A', similarity_score: 0.5, strength: 'possible', same_service: true, ...overrides,
});

describe('rankPastMatches', () => {
  it('puts same service first and keeps the server ranking within each group', () => {
    // Case 2 was ranked above case 3 by the server (e.g. a verified fix, a recent incident) even
    // though it is a little less similar; that order is kept.
    const ranked = rankPastMatches([
      match({ case_id: 1, same_service: false, strength: 'strong', similarity_score: 0.9 }),
      match({ case_id: 2, strength: 'possible', similarity_score: 0.66 }),
      match({ case_id: 3, strength: 'strong', similarity_score: 0.72 }),
      match({ case_id: 5, same_service: false, strength: 'possible', similarity_score: 0.5 }),
      match({ case_id: 4, strength: 'possible', similarity_score: 0.45 }),
    ]);
    expect(ranked.map((item) => item.case_id)).toEqual([2, 3, 4, 1, 5]);
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

  it('folds near-copies under "+N more like this"', () => {
    render(
      <PastCaseMatches
        service="checkout"
        emptyText="none"
        matches={[match({ case_id: 1, title: 'Checkout pool', more_like_this: [match({ case_id: 4, title: 'Checkout pool again', similarity_score: 0.84 })] })]}
      />
    );

    expect(screen.queryByText('Checkout pool again')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('+1 more like this'));
    expect(screen.getByRole('link', { name: 'Checkout pool again' })).toHaveAttribute('href', '/cases/4');
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
