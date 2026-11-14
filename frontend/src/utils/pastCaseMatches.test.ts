import { describe, expect, it } from 'vitest';
import type { PastCaseMatch } from '../types';
import { fixedCountSentence, matchDate, matchOutcome, matchStatus } from './pastCaseMatches';

const match = (overrides: Partial<PastCaseMatch>): PastCaseMatch => ({
  case_id: 1, title: 'A', similarity_score: 0.8, same_service: true, ...overrides,
});

describe('matchOutcome', () => {
  it('leads with the fix when the cause was verified', () => {
    expect(matchOutcome(match({ case_status: 'resolved', rca_verified: true, root_cause_summary: 'Pool too small', corrective_action: 'Raised it' })).parts)
      .toEqual([{ label: 'Fixed', text: 'Raised it' }, { label: 'Cause', text: 'Pool too small' }]);
  });

  it('leads with an unconfirmed cause, so the warning is not hidden behind the fix', () => {
    expect(matchOutcome(match({ case_status: 'resolved', rca_verified: false, root_cause_summary: 'Config change', corrective_action: 'Rolled back' })).parts)
      .toEqual([{ label: 'Likely cause', text: 'Config change', unconfirmed: true }, { label: 'Fixed', text: 'Rolled back' }]);
  });

  it('trusts an imported postmortem without a verified flag', () => {
    expect(matchOutcome(match({ origin: 'imported', case_status: 'resolved', root_cause_summary: 'Cert expired' })).parts)
      .toEqual([{ label: 'Cause', text: 'Cert expired' }]);
  });

  it('says Fix, not Fixed, on a case that is still open', () => {
    expect(matchOutcome(match({ case_status: 'open', corrective_action: 'Raise the pool' })).parts).toEqual([{ label: 'Fix', text: 'Raise the pool' }]);
  });

  it('falls back to the guided investigation, then to saying nothing is recorded', () => {
    expect(matchOutcome(match({ investigation_ending: 'found', investigation_summary: 'Deploy v1.4.2' })).parts).toEqual([{ label: 'Investigating', text: 'Deploy v1.4.2' }]);
    expect(matchOutcome(match({ investigation_ending: 'nothing_found', investigation_summary: 'Looked at deploys' })).parts).toEqual([{ label: 'Investigated', text: 'nothing found yet.' }]);
    expect(matchOutcome(match({ case_status: 'open' }))).toEqual({ parts: [], empty: 'Open, nothing recorded yet.' });
    expect(matchOutcome(match({ case_status: 'resolved' }))).toEqual({ parts: [], empty: 'Resolved, nothing recorded.' });
  });
});

describe('matchStatus', () => {
  it('names the state and, when resolved, whether the cause was verified', () => {
    expect(matchStatus(match({ case_status: 'resolved', rca_verified: true }))).toEqual({ label: 'Resolved', detail: 'cause verified', tone: 'resolved' });
    expect(matchStatus(match({ case_status: 'resolved', rca_verified: false }))).toEqual({ label: 'Resolved', detail: 'cause not verified', tone: 'resolved' });
    expect(matchStatus(match({ case_status: 'resolved', origin: 'imported' }))).toEqual({ label: 'Resolved', detail: 'past incident', tone: 'resolved' });
    expect(matchStatus(match({ case_status: 'in_progress' })).label).toBe('In progress');
    expect(matchStatus(match({})).label).toBe('Open');
  });
});

describe('fixedCountSentence', () => {
  it('counts resolved cases with a fix or outcome', () => {
    const fixed = match({ case_status: 'resolved', corrective_action: 'x' });
    expect(fixedCountSentence([])).toBeNull();
    expect(fixedCountSentence([fixed])).toBe('It was fixed.');
    expect(fixedCountSentence([match({})])).toBe("It wasn't fixed yet.");
    expect(fixedCountSentence([fixed, match({}), match({ case_status: 'resolved' })])).toBe('1 of them was fixed.');
    expect(fixedCountSentence([fixed, fixed])).toBe('2 of them were fixed.');
    expect(fixedCountSentence([match({}), match({})])).toBe('None of them was fixed yet.');
  });
});

describe('matchDate', () => {
  it('drops the year inside the current year and keeps it otherwise', () => {
    const now = new Date('2026-11-14T12:00:00Z');
    expect(matchDate('2026-10-28T12:00:00Z', now)).toMatch(/Oct 28/);
    expect(matchDate('2025-10-28T12:00:00Z', now)).toMatch(/2025/);
    expect(matchDate(null, now)).toBeNull();
    expect(matchDate('not a date', now)).toBeNull();
  });
});
