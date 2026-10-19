import { describe, expect, it } from 'vitest';
import { byLine, scheduleAuthorLine, timeAgo } from './actorLine';

const NOW = Date.parse('2026-10-19T12:00:00Z');

describe('byLine', () => {
  it('names who did it and when, leaving out what is unknown', () => {
    expect(byLine('priya', '2026-10-19T11:50:00Z', NOW)).toBe('by priya · 10m ago');
    expect(byLine(null, '2026-10-19T09:00:00Z', NOW)).toBe('· 3h ago');
    expect(byLine('sam', null, NOW)).toBe('by sam');
    expect(byLine(undefined, undefined, NOW)).toBe('');
  });

  it('rounds to minutes, hours and days', () => {
    expect(timeAgo('2026-10-19T11:59:40Z', NOW)).toBe('just now');
    expect(timeAgo('2026-10-17T12:00:00Z', NOW)).toBe('2d ago');
    expect(timeAgo('not a date', NOW)).toBeNull();
  });
});

describe('scheduleAuthorLine', () => {
  it('names the owner and the last editor', () => {
    expect(scheduleAuthorLine({ created_by: 'sam', edited_by: 'priya', edited_at: '2026-10-18T12:00:00Z' }, NOW)).toBe('Owner sam · last edited by priya · 1d ago');
    expect(scheduleAuthorLine({ created_by: 'sam', edited_by: null }, NOW)).toBe('Owner sam');
    expect(scheduleAuthorLine({ created_by: null, edited_by: null }, NOW)).toBeNull();
  });
});
