import { describe, expect, it } from 'vitest';

// The reverse of standalone/importBoundary.test.ts: the Grafana plugin bundle stays free of the web
// UI's MUI, react-query and router, and of its components and pages. Plugin features re-implement
// their view in plainUi and share only pure code (types, utils, autonomous models).
const files = import.meta.glob(['./**/*.{ts,tsx}', '!./**/*.test.{ts,tsx}'], {
  eager: true,
  query: '?raw',
  import: 'default',
}) as Record<string, string>;

const blocked = [/^@mui\//, /^@tanstack\//, /^react-router/, /^\.\.\/(components|pages|routes|standalone|api)\//];

describe('plugin import boundary', () => {
  it('does not import web UI modules into the Grafana plugin', () => {
    const violations = Object.entries(files).flatMap(([file, content]) =>
      [...content.matchAll(/from\s+'([^']+)'/g)]
        .map((match) => match[1])
        .filter((specifier) => blocked.some((pattern) => pattern.test(specifier)))
        .map((specifier) => `${file} imports ${specifier}`)
    );

    expect(Object.keys(files).length).toBeGreaterThan(10);
    expect(violations).toEqual([]);
  });
});
