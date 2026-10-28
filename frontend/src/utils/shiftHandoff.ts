import type { HandoffWatchItem, ShiftHandoff } from '../types';

// The on-call handoff card, shared by the web UI's Overview and the Grafana plugin's overview.

export const HANDOFF_HOURS = [8, 12, 24] as const;

/** "case #10 · payments / error_rate" or "search / latency_p95". */
export function watchLabel(item: HandoffWatchItem): string {
  const where = [item.service, item.metric_name].filter(Boolean).join(' / ') || item.title;
  return item.case_id ? `Case #${item.case_id} · ${where}` : where;
}

export function handoffCounts(handoff: ShiftHandoff): string {
  const plural = (count: number, noun: string) => `${count} ${noun}${count === 1 ? '' : 's'}`;
  return [
    plural(handoff.new_findings, 'new finding'),
    `${plural(handoff.cases_opened, 'case')} opened`,
    `${handoff.cases_resolved} resolved`,
    `${handoff.cases_still_open} still open`,
  ].join(' · ');
}

/** What Copy for Slack puts on the clipboard: the note (AI's when written, else the plain one) and
 * the list to watch, with links when the page's address is known. */
export function handoffCopyText(handoff: ShiftHandoff, note: string | null | undefined, baseUrl?: string): string {
  const lines = [note?.trim() || handoff.summary];
  if (handoff.watch.length) {
    lines.push('', 'To watch:');
    for (const item of handoff.watch) {
      const link = baseUrl ? ` ${watchHref(item, baseUrl)}` : '';
      lines.push(`- ${watchLabel(item)}: ${item.reason}${link}`);
    }
  }
  return lines.join('\n');
}

/** Web UI address of a watch item; `baseUrl` prefixes it for a pasted link. */
export function watchHref(item: HandoffWatchItem, baseUrl = ''): string {
  if (item.case_id) return `${baseUrl}/cases/${item.case_id}`;
  return `${baseUrl}/findings?window=24h${item.finding_id ? `&finding=${item.finding_id}` : ''}`;
}
