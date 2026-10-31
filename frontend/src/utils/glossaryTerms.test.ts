import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { ALL_GLOSSARY_TERMS, PAGE_GLOSSARY } from './glossaryTerms';

const glossary = readFileSync(resolve(process.cwd(), '../docs/glossary.md'), 'utf-8');
const headings = new Set([...glossary.matchAll(/^### (.+)$/gm)].map((match) => match[1].trim()));

describe("What's what? terms", () => {
  it('are each shortened from a heading in docs/glossary.md', () => {
    const missing = ALL_GLOSSARY_TERMS.filter((item) => !headings.has(item.heading)).map((item) => item.heading);
    expect(missing).toEqual([]);
  });

  it('give every page a few words, none listed twice', () => {
    for (const [page, { terms }] of Object.entries(PAGE_GLOSSARY)) {
      expect(terms.length, page).toBeGreaterThanOrEqual(3);
      expect(new Set(terms.map((item) => item.term)).size, page).toBe(terms.length);
    }
  });
});
