// "by priya · 10m ago": who did something, when it came through Grafana (backend/app/identity.py),
// and when. Older records and anything done elsewhere have no name, and none is guessed.

export function timeAgo(at: string | null | undefined, now: number = Date.now()): string | null {
  if (!at) return null;
  const time = new Date(at).getTime();
  if (Number.isNaN(time)) return null;
  const minutes = Math.max(0, Math.floor((now - time) / 60_000));
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

/** "by priya · 10m ago", "· 10m ago" without a name, "by priya" without a time, "" with neither. */
export function byLine(name: string | null | undefined, at: string | null | undefined, now: number = Date.now()): string {
  const when = timeAgo(at, now);
  return [name ? `by ${name}` : '', when ? `· ${when}` : ''].filter(Boolean).join(' ');
}

/** "Owner sam · last edited by priya · 1d ago" on a schedule; null when neither is known. */
export function scheduleAuthorLine(
  policy: { created_by?: string | null; edited_by?: string | null; edited_at?: string | null },
  now: number = Date.now()
): string | null {
  const parts = [
    policy.created_by ? `Owner ${policy.created_by}` : '',
    policy.edited_by ? `last edited ${byLine(policy.edited_by, policy.edited_at, now)}` : '',
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : null;
}
