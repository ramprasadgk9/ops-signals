import { describe, expect, it } from 'vitest';
import { RELATED_HINT, alertLineHint, aiFooter, hasAiLines, leadSignal, leadSignalText, plainLines, plainParagraph, plainTimes, plainTone } from './findingPlain';
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
      { label: 'Happened with', text: 'Slow-request time (p95) also dropped at Oct 19, 10:54 PM (571 ms to 357 ms).', findingId: 8299, hint: RELATED_HINT },
      { label: 'What to check', text: 'Deploys or config changes in spike-lab between Oct 19, 10:24 PM and 11:24 PM.' },
    ]);
  });

  it('explains how a related finding was chosen', () => {
    expect(RELATED_HINT).toContain('within 10 minutes');
    expect(plainLines(errors, utc).filter((line) => line.hint).map((line) => line.label)).toEqual(['Happened with']);
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

describe('leadSignal', () => {
  const weakFromElsewhere = { id: 'other', summary: 'A weak wobble elsewhere.', analyzer_id: 'anomaly_zscore', confidence: 0.4, importance_score: 0.2 };
  const stretch = { id: 'a', summary: 'A stretch of 16 points unlike anything else.', analyzer_id: 'stumpy', confidence: 1, importance_score: 0.6 };
  const trend = { id: 'b', summary: 'An upward trend.', analyzer_id: 'trend', confidence: 0.7, importance_score: 0.3 };

  it("picks the strongest of the finding's own signals, not the run's first", () => {
    expect(leadSignal(['a', 'b'], [weakFromElsewhere, trend, stretch])).toBe(stretch);
  });

  it("falls back to the run's first signal when the finding names none of them", () => {
    expect(leadSignal(['missing'], [weakFromElsewhere, trend])).toBe(weakFromElsewhere);
    expect(leadSignal(undefined, [])).toBeNull();
  });

  it('writes it as one line with its analyzer and confidence', () => {
    expect(leadSignalText(stretch)).toBe('A stretch of 16 points unlike anything else. (stumpy · confidence 1.00)');
    expect(leadSignalText(null)).toBeNull();
  });
});

describe('plainLines with AI wording', () => {
  const ai = {
    available: true,
    why: 'Fewer requests now fail, so most users get through again.',
    check_extra: 'Whether the fix is still in place after the next release.',
    related_extra: 'Errors and slow requests dropping together often means a shared dependency recovered.',
    model: 'qwen2.5:3b',
  };

  it('replaces why, and adds its sentence after the template check and the first Happened with', () => {
    expect(plainLines(errors, utc, ai)).toEqual([
      { label: 'Why it matters', text: ai.why, ai: true },
      {
        label: 'Happened with',
        text: `Slow-request time (p95) also dropped at Oct 19, 10:54 PM (571 ms to 357 ms). ${ai.related_extra}`,
        findingId: 8299,
        hint: RELATED_HINT,
        ai: true,
      },
      { label: 'What to check', text: `Deploys or config changes in spike-lab between Oct 19, 10:24 PM and 11:24 PM. ${ai.check_extra}`, ai: true },
    ]);
  });

  it('keeps the template for each line the AI left out', () => {
    const lines = plainLines(errors, utc, { available: true, why: null, check_extra: ai.check_extra, related_extra: null });
    expect(lines[0]).toEqual({ label: 'Why it matters', text: 'Fewer requests fail, so fewer users see errors.' });
    expect(lines[1].ai).toBeUndefined();
    expect(lines[2].ai).toBe(true);
  });

  it('shows the template when nothing is available', () => {
    expect(plainLines(errors, utc, { available: false, reason: 'ai_off' })).toEqual(plainLines(errors, utc));
    expect(hasAiLines({ available: false, reason: 'ai_off' })).toBe(false);
    expect(hasAiLines({ available: true, why: null, check_extra: null, related_extra: null })).toBe(false);
    expect(hasAiLines(ai)).toBe(true);
  });

  it('names the model in the footer', () => {
    expect(aiFooter(ai)).toBe("Written by AI (qwen2.5:3b) from this finding's facts");
    expect(aiFooter({ ...ai, model: null })).toBe("Written by AI from this finding's facts");
  });
});

describe('alert context', () => {
  const withAlert: FindingPlain = {
    ...errors,
    related: [],
    alert: {
      name: 'SpikeLabErrorRateHigh',
      group: 'lab-alerts',
      summary: 'spike-lab error rate above 5%',
      text: 'Orders fail at checkout.',
      runbook_url: 'https://wiki.example.com/runbooks/spike-lab-errors',
      line: 'Back below the 5% alert line since [[time:2026-10-19T22:54:17Z]].',
      line_alert: 'SpikeLabErrorRateHigh',
    },
  };
  const hint = alertLineHint('SpikeLabErrorRateHigh');

  it("adds the alert line, takes the alert's words for why it matters, and ends with the runbook", () => {
    expect(plainLines(withAlert, utc)).toEqual([
      { label: 'Alert line', text: 'Back below the 5% alert line since Oct 19, 10:54 PM.', hint: alertLineHint('SpikeLabErrorRateHigh', 'spike-lab error rate above 5%') },
      { label: 'Why it matters', text: 'Orders fail at checkout.', hint },
      { label: 'What to check', text: 'Deploys or config changes in spike-lab between Oct 19, 10:24 PM and 11:24 PM.' },
      { label: 'Runbook', text: '(from alert SpikeLabErrorRateHigh)', href: 'https://wiki.example.com/runbooks/spike-lab-errors', linkText: 'Open the runbook', hint },
    ]);
  });

  it("names the alert's summary in the Alert line tooltip", () => {
    expect(alertLineHint('A', 'p95 above 300ms')).toBe('From the Prometheus alert A ("p95 above 300ms"), as it is now: written by the team that set it up, not by Ops Signals.');
    expect(alertLineHint('A')).toBe('From the Prometheus alert A, as it is now: written by the team that set it up, not by Ops Signals.');
  });

  it("keeps the team's words over AI wording", () => {
    const ai = { available: true, why: 'AI why.', check_extra: null, related_extra: null, model: 'm' };
    expect(plainLines(withAlert, utc, ai).find((line) => line.label === 'Why it matters')?.text).toBe('Orders fail at checkout.');
  });

  it('falls back to the template why without alert text, and never links a non-web runbook', () => {
    const lines = plainLines({ ...withAlert, alert: { ...withAlert.alert!, text: null, runbook_url: 'javascript:alert(1)' } }, utc);
    expect(lines.find((line) => line.label === 'Why it matters')?.text).toBe(errors.why);
    expect(lines.some((line) => line.label === 'Runbook')).toBe(false);
  });

  it('puts the alert line and words in the one-paragraph summary', () => {
    expect(plainParagraph(withAlert, utc)).toBe(
      'Better: Error rate dropped sharply and stayed lower. About 11.3% until Oct 19, 10:54 PM. Since then about 1.2% (down 89%). Back below the 5% alert line since Oct 19, 10:54 PM. Orders fail at checkout.',
    );
  });
});
