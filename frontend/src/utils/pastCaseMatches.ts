import type { PastCaseMatch } from '../types';

/** Same service first; within each group, the server's order. The backend ranks matches by
 * similarity plus small bonuses (shared keywords, verified root cause, recency), so re-sorting by
 * score here would undo that. A possible match on this service is more useful than a strong-looking
 * one elsewhere. Shared by the web UI and the Grafana plugin so both list matches the same way. */
export function rankPastMatches(matches: PastCaseMatch[]) {
  return [...matches].sort((a, b) => Number(Boolean(b.same_service)) - Number(Boolean(a.same_service)));
}
