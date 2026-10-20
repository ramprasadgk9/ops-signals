// Plain-words wording for a finding card (backend services/finding_plain.py, wording in
// config/finding_templates.yaml). Shared by the web UI and the Grafana plugin, so no MUI here.
import type { FindingPlain, FindingPlainBadge } from '../types';

const TIME_MARKER = /\[\[time:([^\]]+)\]\]/g;

export type PlainTone = 'bad' | 'good' | 'gap' | 'neutral';

const TONES: Record<FindingPlainBadge, PlainTone> = {
  worse: 'bad',
  better: 'good',
  gap: 'gap',
  blip: 'neutral',
  noise: 'neutral',
  changed: 'neutral',
};

export function plainTone(badge: FindingPlainBadge | string | undefined): PlainTone {
  return TONES[badge as FindingPlainBadge] ?? 'neutral';
}

function dayKey(moment: Date, timeZone?: string): string {
  return moment.toLocaleDateString('en-CA', { timeZone });
}

/**
 * Replaces each time marker with the moment in the reader's time zone ("Oct 19, 10:54 PM"). A
 * later marker on the same day as the one before it shows the time only ("between Oct 19,
 * 10:24 PM and 11:24 PM"). `timeZone` and `locale` exist for tests.
 */
export function plainTimes(text: string | null | undefined, options: { locale?: string; timeZone?: string } = {}): string {
  if (!text) return '';
  let previousDay: string | null = null;
  return text.replace(TIME_MARKER, (marker, iso: string) => {
    const moment = new Date(iso);
    if (Number.isNaN(moment.getTime())) return marker;
    const day = dayKey(moment, options.timeZone);
    const time = moment.toLocaleTimeString(options.locale, { hour: 'numeric', minute: '2-digit', timeZone: options.timeZone });
    const shown = day === previousDay ? time : `${moment.toLocaleDateString(options.locale, { month: 'short', day: 'numeric', timeZone: options.timeZone })}, ${time}`;
    previousDay = day;
    return shown;
  });
}

export type PlainLine = { label: string; text: string; findingId?: number | null };

/** The lines under the headline, in card order, with times shown in the reader's time zone. */
export function plainLines(plain: FindingPlain, options: { locale?: string; timeZone?: string } = {}): PlainLine[] {
  const lines: PlainLine[] = [];
  if (plain.why) lines.push({ label: 'Why it matters', text: plainTimes(plain.why, options) });
  for (const item of plain.related ?? []) lines.push({ label: 'Happened with', text: plainTimes(item.text, options), findingId: item.finding_id });
  if (plain.check) lines.push({ label: 'What to check', text: plainTimes(plain.check, options) });
  return lines;
}

/** One paragraph for places that show a single line of text (the assistant, copied summaries). */
export function plainParagraph(plain: FindingPlain | null | undefined, options: { locale?: string; timeZone?: string } = {}): string | null {
  if (!plain) return null;
  return [`${plain.badge_label}: ${plain.headline}.`, plainTimes(plain.what, options), plainTimes(plain.why, options)].filter(Boolean).join(' ');
}
