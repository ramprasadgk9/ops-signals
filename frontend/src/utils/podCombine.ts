import type { CombineChoice } from '../types';

/** Pod combine choices in the order they are offered. Shared by the web UI and the Grafana plugin. */
export const COMBINE_ORDER: CombineChoice[] = ['max', 'sum', 'avg', 'min'];

export function combineName(how: CombineChoice, label: string): string {
  const plural = `${label}s`;
  if (how === 'sum') return `All ${plural} added up`;
  if (how === 'avg') return `Average ${label}`;
  if (how === 'max') return `Highest ${label}`;
  return `Lowest ${label}`;
}

/** "the average of 4 pods", for saying what a run analyzed. */
export function combinedPhrase(how: CombineChoice, label: string, count: number): string {
  if (how === 'sum') return `all ${count} ${label}s added up`;
  return `the ${{ max: 'highest', avg: 'average', min: 'lowest' }[how]} of ${count} ${label}s`;
}
