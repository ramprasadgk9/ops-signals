// Plain-language wording for a finding's trust (backend services/finding_trust.py, docs/finding-trust.md).
import { byLine } from './actorLine';
import type { Finding, FindingTrust, FindingVerdict } from '../types';

type ChipColor = 'success' | 'warning' | 'error' | 'default';

const BADGES: Record<NonNullable<FindingTrust['badge']>, { label: string; color: ChipColor; detail: string }> = {
  strong: {
    label: 'Strong evidence',
    color: 'success',
    detail: 'Two different checks agree: the values look unusual and the level moved and stayed there.',
  },
  moderate: {
    label: 'Moderate evidence',
    color: 'warning',
    detail: 'One check saw the level move and stay there. Worth a look.',
  },
  team_confirmed: {
    label: 'Confirmed by your team',
    color: 'success',
    detail: 'Usually not an alert, but your team said findings like this on this service were real, so they show here.',
  },
  data_problem: {
    label: 'Data problem',
    color: 'error',
    detail: 'The data itself stopped arriving or froze at one value. Fix this before trusting other findings on the metric.',
  },
};

export const VERDICTS: Array<{ id: FindingVerdict; label: string }> = [
  { id: 'real_problem', label: 'Real problem' },
  { id: 'expected_change', label: 'Expected change' },
  { id: 'not_a_problem', label: 'Not a problem' },
];

export function trustBadge(trust?: FindingTrust | null): { label: string; color: ChipColor; detail: string } | null {
  if (!trust) return null;
  if (trust.badge) return BADGES[trust.badge];
  if (trust.moved === 'down') {
    return {
      label: 'Usually not a problem here',
      color: 'default',
      detail: 'Your team said most findings like this on this service were not a problem, so they moved to Context only.',
    };
  }
  return {
    label: 'Context only',
    color: 'default',
    detail: 'Not an alert. In tests, findings like this were real about as often as a random alert. Useful when you are already investigating.',
  };
}

export function needsAttention(finding: Finding): boolean {
  // Without trust (an older API) every finding stays in the main list, as before.
  return !finding.trust || finding.trust.tier === 'needs_attention';
}

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function testedHeadline(trust: FindingTrust): string {
  if (trust.tested) return `${pct(trust.tested.real)} were real`;
  return trust.group === 'data_problem' ? 'This is a fact' : 'Not tested';
}

export function testedCaption(trust: FindingTrust): string {
  const tested = trust.tested;
  if (!tested) {
    return trust.group === 'data_problem'
      ? 'No data points arrived, or the value froze. It is not a guess, so there is no tested rate.'
      : 'Not enough findings like this were checked to show a number.';
  }
  const fit = tested.fits_metric ? '' : ` · tested on ${tested.data_kind} CPU, memory and latency, not metrics like this one`;
  return `${tested.checked} checked in tests${fit}`;
}

export function testedTooltip(trust: FindingTrust): string {
  const tested = trust.tested;
  if (!tested) return '';
  return (
    `Tested on public ${tested.data_kind} data where problems were marked at known times (${tested.dataset}` +
    `${tested.measured_at ? `, measured ${tested.measured_at}` : ''}). An alert at a random moment would have been right ` +
    `${pct(tested.random)} of the time. Your team's answers replace this number once ${trust.service.min_answers} findings like this are answered.`
  );
}

/** Answers on a finding with no service label count per metric (backend finding_trust.py). */
function byMetric(trust: FindingTrust): boolean {
  return trust.service.scope === 'metric';
}

function placeName(trust: FindingTrust, service?: string | null): string {
  return byMetric(trust) ? 'this metric' : service ?? 'this service';
}

export function serviceLabel(trust: FindingTrust): string {
  return byMetric(trust) ? 'On this metric' : 'On your service';
}

export function serviceHeadline(trust: FindingTrust): string {
  const { real, answered, min_answers: needed } = trust.service;
  return answered < needed ? `${answered} of ${needed} answers` : `${real} of ${answered} were real`;
}

export function serviceCaption(trust: FindingTrust, service?: string | null): string {
  const { answered, min_answers: needed } = trust.service;
  const where = placeName(trust, service);
  const why = byMetric(trust) ? ' It has no service label, so answers count per metric.' : '';
  if (answered < needed) {
    return `${needed - answered} more "Real problem" or "Not a problem" answers on findings like this on ${where}, and your team's own rate shows here.${why}`;
  }
  return `Findings like this on ${where} that your team answered.${why}`;
}

/** The bar under the headline: progress towards enough answers, then the share that were real. */
export function serviceProgress(trust: FindingTrust): number {
  const { real, answered, min_answers: needed } = trust.service;
  return answered < needed ? answered / needed : real / answered;
}

/** Why the team's answers moved this kind of finding to the other list; null when they didn't. */
export function movedNote(trust: FindingTrust, service?: string | null): string | null {
  const { real, answered } = trust.service;
  const where = placeName(trust, service);
  if (trust.moved === 'up') return `Moved to Needs attention: your team said ${real} of ${answered} findings like this on ${where} were real.`;
  if (trust.moved === 'down') return `Moved to Context only: your team said only ${real} of ${answered} findings like this on ${where} were real.`;
  return null;
}

/** Your team's own rate once it has enough answers, else the tested one: the number to lead with. */
export function serviceRateLeads(trust: FindingTrust): boolean {
  return trust.service.answered >= trust.service.min_answers;
}

/** "Answered Expected change by priya · 10m ago" under the "Was this real?" buttons; null when there
 * is no answer, or nothing to add to the highlighted button (an older backend sends neither). */
export function answerLine(trust: FindingTrust | null | undefined, now: number = Date.now()): string | null {
  if (!trust?.your_answer) return null;
  const rest = byLine(trust.answered_by, trust.answered_at, now);
  if (!rest) return null;
  const label = VERDICTS.find((verdict) => verdict.id === trust.your_answer)?.label ?? trust.your_answer;
  return `Answered ${label} ${rest}`;
}
