import { describe, expect, it } from 'vitest';

const files = import.meta.glob('../{components,pages,routes,standalone}/**/*.{ts,tsx}', {
  eager: true,
  query: '?raw',
  import: 'default',
}) as Record<string, string>;

const blockedFragments = ['../' + 'grafana', '../' + 'panel', '../' + 'plugin', './' + 'grafana', './' + 'panel', './' + 'plugin', '@' + 'grafana/'];

describe('standalone import boundary', () => {
  it('does not import Grafana runtime or plugin-only modules into standalone code', () => {
    const violations = Object.entries(files).flatMap(([file, content]) => {
      if (file.endsWith('importBoundary.test.ts')) return [];
      return blockedFragments
        .filter((blocked) => content.includes(blocked))
        .map((blocked) => `${file} imports ${blocked}`);
    });

    expect(violations).toEqual([]);
  });
});
