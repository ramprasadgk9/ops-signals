import type { ReactElement } from 'react';
import { fireEvent, render as rtlRender, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { PastCaseMatches, rankPastMatches } from './PastCaseMatches';
import type { PastCaseMatch } from '../types';

// Match titles and the Open case link navigate inside the app.
const render = (ui: ReactElement) => rtlRender(<MemoryRouter>{ui}</MemoryRouter>);

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

  it('says when a past case was resolved without a verified root cause', () => {
    render(
      <PastCaseMatches
        service="checkout"
        emptyText="none"
        matches={[
          match({ case_id: 1, title: 'Unverified', case_status: 'resolved', rca_verified: false, root_cause_summary: 'db query issues' }),
          match({ case_id: 2, title: 'Verified', case_status: 'resolved', rca_verified: true, root_cause_summary: 'missing index' }),
        ]}
      />
    );

    const [unverified, verified] = screen.getAllByTestId('past-case-outcome');
    expect(unverified).toHaveTextContent('Likely cause (unconfirmed): db query issues');
    expect(verified).toHaveTextContent('Cause: missing index');
    expect(verified).not.toHaveTextContent('unconfirmed');
  });

  it('links each match to its case and says what state the case is in', () => {
    render(
      <PastCaseMatches
        service="checkout"
        emptyText="none"
        matches={[
          match({ case_id: 8, title: 'Stuck exporter', case_status: 'resolved', rca_verified: true, root_cause_summary: 'Exporter hung', corrective_action: 'Restarted it', opened_at: '2026-10-28T10:00:00Z' }),
          match({ case_id: 14, title: 'Shifted up', case_status: 'in_progress', investigation_ending: 'found', investigation_summary: 'Pointed at deploy v1.4.2.' }),
          match({ case_id: 17, title: 'Stuck again', case_status: 'open' }),
        ]}
      />
    );

    expect(screen.getByTestId('past-case-fixed-count')).toHaveTextContent('1 of them was fixed.');
    expect(screen.getByRole('link', { name: 'Case #8 · Open case →' })).toHaveAttribute('href', '/cases/8');
    const [fixed, investigating, open] = screen.getAllByTestId('past-case-match');
    expect(fixed).toHaveTextContent('Fixed: Restarted it Cause: Exporter hung');
    expect(fixed).toHaveTextContent('Resolved · cause verified');
    expect(fixed).toHaveTextContent('Oct 28');
    expect(investigating).toHaveTextContent('Investigating: Pointed at deploy v1.4.2.');
    expect(investigating).toHaveTextContent('In progress');
    expect(open).toHaveTextContent('Open, nothing recorded yet.');
  });
});
