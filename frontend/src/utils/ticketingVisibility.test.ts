import { describe, expect, it } from 'vitest';
import { shouldShowTicketCard } from './ticketingVisibility';

describe('shouldShowTicketCard', () => {
  it('hides ticket actions while ticketing is off and nothing is linked', () => {
    expect(shouldShowTicketCard({ enabled: false }, false, null)).toBe(false);
  });

  it('waits for the status before showing anything', () => {
    expect(shouldShowTicketCard(undefined, false, null)).toBe(false);
  });

  it('shows them when ticketing is on', () => {
    expect(shouldShowTicketCard({ enabled: true }, false, null)).toBe(true);
  });

  it('keeps an already linked ticket visible after ticketing is turned off', () => {
    expect(shouldShowTicketCard({ enabled: false }, false, { display_key: 'OPS-1' })).toBe(true);
  });

  it('falls back to showing them when the status endpoint is unavailable (older backend)', () => {
    expect(shouldShowTicketCard(undefined, true, null)).toBe(true);
  });
});
