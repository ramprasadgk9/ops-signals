import { describe, expect, it } from 'vitest';
import { afterDays, cameBackHeadline, daysBadge, didNotHoldHeadline } from './fixCameBack';

const cameBack = { case_id: 5, title: 'Checkout slow', fixed_at: '2026-10-24T15:10:00', days: 3, fix: 'Rolled back.' };

describe('fix came back wording', () => {
  it('says how soon in plain words', () => {
    expect(afterDays(0)).toBe('less than a day');
    expect(afterDays(1)).toBe('1 day');
    expect(daysBadge(0)).toEqual({ value: '<1', unit: 'day' });
    expect(daysBadge(12)).toEqual({ value: '12', unit: 'days' });
  });

  it('names the old case only on a case page', () => {
    expect(cameBackHeadline(cameBack)).toBe('This came back 3 days after it was fixed.');
    expect(cameBackHeadline(cameBack, true)).toBe('This came back 3 days after case #5 was fixed.');
  });

  it('says nothing about a fix that held or is too new to judge', () => {
    expect(didNotHoldHeadline({ status: 'held', label: 'Held for 30+ days' })).toBeNull();
    expect(didNotHoldHeadline({ status: 'came_back', label: 'Came back after 1 day', came_back_case_id: 9, came_back_after_days: 1 }))
      .toBe("This fix didn't hold: the problem came back 1 day later in case #9.");
  });
});
