// Plain-words wording for a finding card (backend services/finding_plain.py, wording in
// config/finding_templates.yaml). Shared by the web UI and the Grafana plugin, so no MUI here.
import type { FindingAIWording, FindingPlain, FindingPlainBadge } from '../types';

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

export type PlainLine = { label: string; text: string; findingId?: number | null; hint?: string; /** Written or extended by the AI provider. */ ai?: true };

/** Tooltip on "Happened with": how the other finding was chosen. The 10 minutes is
 * RELATED_WINDOW in backend/app/services/finding_plain.py; docs/finding-wording.md explains it. */
export const RELATED_HINT =
  'Another finding on this service: a different metric that also rose or dropped and stayed there, ' +
  'within 10 minutes of this change. Changes at the same moment often share one cause, such as a deploy, ' +
  'a restart or a traffic move. Spikes, trends and stuck values have no single moment, so they are not matched.';

/** Tooltip on the AI chip of a line the AI provider wrote (backend/app/services/finding_ai_wording.py). */
export const AI_LINE_HINT = "Written by AI for this metric and service, using only this finding's facts. Numbers and names it adds are checked against them.";

/** Whether the AI provider wrote any line for this finding. */
export function hasAiLines(ai: FindingAIWording | null | undefined): boolean {
  return Boolean(ai?.available && (ai.why || ai.check_extra || ai.related_extra));
}

/** The lines under the headline, in card order, with times shown in the reader's time zone. The
 * target comes first: against a target the team set, the finding is a fact about their service.
 * With AI wording, its why replaces the template's, and its extra check and Happened with sentences
 * follow the template's, so the template's facts and the link to the other finding stay. */
export function plainLines(plain: FindingPlain, options: { locale?: string; timeZone?: string } = {}, ai?: FindingAIWording | null): PlainLine[] {
  const lines: PlainLine[] = [];
  const written = ai?.available ? ai : null;
  if (plain.target) lines.push({ label: 'Your target', text: plainTimes(plain.target, options) });
  if (written?.why) lines.push({ label: 'Why it matters', text: written.why, ai: true });
  else if (plain.why) lines.push({ label: 'Why it matters', text: plainTimes(plain.why, options) });
  if (plain.service_about) lines.push({ label: 'This service', text: plain.service_about });
  (plain.related ?? []).forEach((item, index) => {
    const line: PlainLine = { label: 'Happened with', text: plainTimes(item.text, options), findingId: item.finding_id, hint: RELATED_HINT };
    lines.push(index === 0 && written?.related_extra ? { ...line, text: `${line.text} ${written.related_extra}`, ai: true } : line);
  });
  const check = plain.check ? plainTimes(plain.check, options) : '';
  if (written?.check_extra) lines.push({ label: 'What to check', text: check ? `${check} ${written.check_extra}` : written.check_extra, ai: true });
  else if (check) lines.push({ label: 'What to check', text: check });
  return lines;
}

/** The footer under AI-written lines: which model wrote them. */
export function aiFooter(ai: FindingAIWording): string {
  return `Written by AI${ai.model ? ` (${ai.model})` : ''} from this finding's facts`;
}

/** How to turn the AI provider on, for the hint shown to admins when it's off. Same steps as the
 * README's "Optional: Enable Local AI" (docker-compose.yml profile "ai", backend/app/ai/config.py). */
export const AI_SETUP = {
  intro: "With AI on, finding details get Why it matters, What to check and Happened with written for the metric and service, not the same sentence for every finding of a kind. Everything else works the same with it off.",
  steps: [
    { text: 'Start a local model. Nothing leaves your network and no API key is needed. The first start downloads qwen2.5:3b (about 2 GB).', command: 'docker compose --profile ai up -d' },
    { text: "Turn it on for the backend: add these to .env (or the backend's environment) and restart the backend.", command: 'OPS_SIGNALS_AI_ENABLED=1\nOPS_SIGNALS_AI_PROVIDER=ollama' },
    { text: 'Open a finding again. Its lines are written the first time it opens, then saved.', command: null },
  ],
  other: 'Already run a model somewhere else? See "Other AI Providers" in docs/ask-ops-signals-assistant.md.',
} as const;

/** Where the "turn on AI" hint remembers it was dismissed, in this browser. */
export const AI_HINT_DISMISSED_KEY = 'ops-signals.ai-wording-hint-dismissed';

export function aiHintDismissed(): boolean {
  try {
    return window.localStorage.getItem(AI_HINT_DISMISSED_KEY) === '1';
  } catch {
    return false;
  }
}

export function dismissAiHint(): void {
  try {
    window.localStorage.setItem(AI_HINT_DISMISSED_KEY, '1');
  } catch {
    // Private window or blocked storage: the hint shows again next time, nothing else changes.
  }
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
