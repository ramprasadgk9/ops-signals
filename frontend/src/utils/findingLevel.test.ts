import { describe, expect, it } from 'vitest';
import { findingLevel, findingLevelHint } from './findingLevel';

describe('findingLevel', () => {
  it('shows importance levels as High, Medium and Low', () => {
    expect(findingLevel('critical')).toMatchObject({ label: 'High', chip: 'error' });
    expect(findingLevel('significant')).toMatchObject({ label: 'Medium', chip: 'warning' });
    expect(findingLevel('NORMAL')).toMatchObject({ label: 'Low', chip: 'default' });
  });

  it('never shows a low-importance finding as healthy', () => {
    expect(findingLevel('normal').chip).not.toBe('success');
    expect(findingLevelHint('normal')).toContain('a change was found');
  });

  it('keeps unknown values readable', () => {
    expect(findingLevel('warning').label).toBe('Warning');
    expect(findingLevel(undefined).label).toBe('Unknown');
  });
});
