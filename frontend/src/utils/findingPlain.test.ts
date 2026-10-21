import { describe, expect, it } from 'vitest';
import { plainLines, plainParagraph, plainTimes, plainTone } from './findingPlain';
import type { FindingPlain } from '../types';

// Finding #8300 as the backend words it (tests/test_finding_plain.py).
const errors: FindingPlain = {
  kind: 'level_change',
  badge: 'better',
  badge_label: 'Better',
  headline: 'Error rate dropped sharply and stayed lower',
  what: 'About 11.3% until [[time:2026-10-19T22:54:17Z]]. Since then about 1.2% (down 89%).',
  why: 'Fewer requests fail, so fewer users see errors.',
  check: 'Deploys or config changes in spike-lab between [[time:2026-10-19T22:24:17Z]] and [[time:2026-10-19T23:24:17Z]].',
  change_time: '[[time:2026-10-19T22:54:17Z]]',
  related: [{ finding_id: 8299, text: 'Slow-request time (p95) also dropped at [[time:2026-10-19T22:54:17Z]] (571 ms to 357 ms).' }],
};
const utc = { locale: 'en-US', timeZone: 'UTC' };

describe('plainTimes', () => {
  it("shows each time in the reader's time zone", () => {
    expect(plainTimes(errors.what, utc)).toBe('About 11.3% until Oct 19, 10:54 PM. Since then about 1.2% (down 89%).');
    expect(plainTimes(errors.what, { locale: 'en-US', timeZone: 'Asia/Kolkata' })).toContain('Oct 20, 4:24 AM');
  });

  it('drops the date from a second time on the same day', () => {
    expect(plainTimes(errors.check, utc)).toBe('Deploys or config changes in spike-lab between Oct 19, 10:24 PM and 11:24 PM.');
  });

  it('leaves text without markers alone and tolerates a bad marker', () => {
    expect(plainTimes('No times here.', utc)).toBe('No times here.');
    expect(plainTimes('At [[time:not-a-time]].', utc)).toBe('At [[time:not-a-time]].');
    expect(plainTimes(null)).toBe('');
  });
});

describe('plainLines', () => {
  it('lists why, the related changes and what to check, in that order', () => {
    expect(plainLines(errors, utc)).toEqual([
      { label: 'Why it matters', text: 'Fewer requests fail, so fewer users see errors.' },
      { label: 'Happened with', text: 'Slow-request time (p95) also dropped at Oct 19, 10:54 PM (571 ms to 357 ms).', findingId: 8299 },
      { label: 'What to check', text: 'Deploys or config changes in spike-lab between Oct 19, 10:24 PM and 11:24 PM.' },
    ]);
  });

  it('skips lines the finding has no value for', () => {
    expect(plainLines({ ...errors, why: null, check: undefined, related: [] }, utc)).toEqual([]);
  });
});

describe('service context', () => {
  const payments: FindingPlain = {
    ...errors,
    badge: 'worse',
    badge_label: 'Worse',
    related: [],
    check: null,
    target: 'Above your 1% target since [[time:2026-10-19T22:54:17Z]] (2 hours so far).',
    service_about: 'Customers pay for their orders here.',
    service_importance: 'critical',
    service_importance_label: 'Critical service',
  };

  it('puts the target first and says what the service does after why it matters', () => {
    expect(plainLines(payments, utc)).toEqual([
      { label: 'Your target', text: 'Above your 1% target since Oct 19, 10:54 PM (2 hours so far).' },
      { label: 'Why it matters', text: 'Fewer requests fail, so fewer users see errors.' },
      { label: 'This service', text: 'Customers pay for their orders here.' },
    ]);
  });

  it('includes the target in the one-paragraph version', () => {
    expect(plainParagraph(payments, utc)).toContain('(down 89%). Above your 1% target since Oct 19, 10:54 PM (2 hours so far). Fewer');
  });
});

describe('plainParagraph and plainTone', () => {
  it('reads as one paragraph for single-line places', () => {
    expect(plainParagraph(errors, utc)).toBe(
      'Better: Error rate dropped sharply and stayed lower. About 11.3% until Oct 19, 10:54 PM. Since then about 1.2% (down 89%). Fewer requests fail, so fewer users see errors.',
    );
    expect(plainParagraph(null)).toBeNull();
  });

  it('gives each badge a tone, unknown ones neutral', () => {
    expect([plainTone('worse'), plainTone('better'), plainTone('gap'), plainTone('noise'), plainTone('whatever')]).toEqual(['bad', 'good', 'gap', 'neutral', 'neutral']);
  });
});
