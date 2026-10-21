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

export type PlainLine = { label: string; text: string; findingId?: number | null; hint?: string };

/** Tooltip on "Happened with": how the other finding was chosen. The 10 minutes is
 * RELATED_WINDOW in backend/app/services/finding_plain.py; docs/finding-wording.md explains it. */
export const RELATED_HINT =
  'Another finding on this service: a different metric that also rose or dropped and stayed there, ' +
  'within 10 minutes of this change. Changes at the same moment often share one cause, such as a deploy, ' +
  'a restart or a traffic move. Spikes, trends and stuck values have no single moment, so they are not matched.';

/** The lines under the headline, in card order, with times shown in the reader's time zone. The
 * target comes first: against a target the team set, the finding is a fact about their service. */
export function plainLines(plain: FindingPlain, options: { locale?: string; timeZone?: string } = {}): PlainLine[] {
  const lines: PlainLine[] = [];
  if (plain.target) lines.push({ label: 'Your target', text: plainTimes(plain.target, options) });
  if (plain.why) lines.push({ label: 'Why it matters', text: plainTimes(plain.why, options) });
  if (plain.service_about) lines.push({ label: 'This service', text: plain.service_about });
  for (const item of plain.related ?? []) lines.push({ label: 'Happened with', text: plainTimes(item.text, options), findingId: item.finding_id, hint: RELATED_HINT });
  if (plain.check) lines.push({ label: 'What to check', text: plainTimes(plain.check, options) });
  return lines;
}

/** One paragraph for places that show a single line of text (the assistant, copied summaries). */
export function plainParagraph(plain: FindingPlain | null | undefined, options: { locale?: string; timeZone?: string } = {}): string | null {
  if (!plain) return null;
  return [`${plain.badge_label}: ${plain.headline}.`, plainTimes(plain.what, options), plainTimes(plain.target, options), plainTimes(plain.why, options)].filter(Boolean).join(' ');
}

export type LeadSignal = { id?: string; summary?: string | null; signal_type?: string; analyzer_id?: string | null; confidence?: number | null; importance_score?: number | null };

/**
 * The signal that best stands for a finding: the strongest of its own signals (importance, then
 * confidence). Falls back to the run's first signal only when the finding names none that were
 * returned, so a weak signal from elsewhere in the run doesn't stand in for the finding.
 */
export function leadSignal<T extends LeadSignal>(signalIds: string[] | undefined, signals: T[]): T | null {
  const own = signals.filter((signal) => signal.id !== undefined && (signalIds ?? []).includes(signal.id));
  if (!own.length) return signals[0] ?? null;
  return [...own].sort((a, b) => (b.importance_score ?? 0) - (a.importance_score ?? 0) || (b.confidence ?? 0) - (a.confidence ?? 0))[0];
}

/** One line for the signal under Technical details: "<summary> (stumpy · confidence 1.00)". */
export function leadSignalText(signal: LeadSignal | null | undefined): string | null {
  if (!signal) return null;
  const confidence = typeof signal.confidence === 'number' ? ` · confidence ${signal.confidence.toFixed(2)}` : '';
  return `${signal.summary ?? signal.signal_type ?? 'Signal'} (${signal.analyzer_id ?? 'unknown analyzer'}${confidence})`;
}
