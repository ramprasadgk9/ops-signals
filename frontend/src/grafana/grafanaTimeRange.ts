export type GrafanaTimeRange = {
  from: Date;
  to: Date;
  display: string;
};

function formatDisplay(from: Date, to: Date) {
  return `${from.toLocaleString()} - ${to.toLocaleString()}`;
}

function parseRelativeNow(value: string, now: Date) {
  if (value === 'now') return now;
  const match = value.match(/^now-(\d+)([mhdw])$/);
  if (!match) return null;
  const amount = Number(match[1]);
  const unit = match[2];
  const ms =
    unit === 'm' ? amount * 60 * 1000 :
    unit === 'h' ? amount * 60 * 60 * 1000 :
    unit === 'd' ? amount * 24 * 60 * 60 * 1000 :
    amount * 7 * 24 * 60 * 60 * 1000;
  return new Date(now.getTime() - ms);
}

function parseGrafanaTime(value: string | null, fallback: Date, now: Date) {
  if (!value) return fallback;
  const relative = parseRelativeNow(value, now);
  if (relative) return relative;
  const numeric = Number(value);
  if (Number.isFinite(numeric)) {
    return new Date(numeric > 1e11 ? numeric : numeric * 1000);
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? fallback : parsed;
}

export function readGrafanaTimeRange(): GrafanaTimeRange {
  const now = new Date();
  const params = new URLSearchParams(window.location.search);
  const to = parseGrafanaTime(params.get('to'), now, now);
  const from = parseGrafanaTime(params.get('from'), new Date(to.getTime() - 6 * 60 * 60 * 1000), now);
  return buildTimeRange(from, to);
}

export function calculateIntervalMs(range: GrafanaTimeRange, maxDataPoints = 1000) {
  const durationMs = Math.max(range.to.getTime() - range.from.getTime(), 60 * 1000);
  return Math.max(Math.ceil(durationMs / maxDataPoints), 15 * 1000);
}

export function buildTimeRange(from: Date, to: Date): GrafanaTimeRange {
  return {
    from,
    to,
    display: formatDisplay(from, to),
  };
}

export function formatDateTimeLocal(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  const hours = String(value.getHours()).padStart(2, '0');
  const minutes = String(value.getMinutes()).padStart(2, '0');
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

export function parseDateTimeLocal(value: string) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function createRelativeTimeRange(hours: number): GrafanaTimeRange {
  const to = new Date();
  const from = new Date(to.getTime() - hours * 60 * 60 * 1000);
  return buildTimeRange(from, to);
}
