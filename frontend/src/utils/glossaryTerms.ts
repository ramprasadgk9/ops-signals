// What's what?: the words people found too broad, explained on the pages that use them. The text is
// docs/glossary.md shortened; each term names its glossary heading so the two stay in step.

export const GLOSSARY_URL = 'https://github.com/ramprasadgk9/ops-signals/blob/main/docs/glossary.md';

export type ChainStep = 'signal' | 'finding' | 'case' | 'memory';
export type GlossaryPage = 'findings' | 'cases' | 'behavior' | 'recurring' | 'overview';

export const CHAIN_INTRO = 'Ops Signals goes from signal to finding to case to memory.';

export const CHAIN: Array<{ step: ChainStep; title: string; text: string; who: string }> = [
  { step: 'signal', title: 'Signal', text: "One analyzer's raw output on one metric.", who: 'Ops Signals · rarely shown' },
  { step: 'finding', title: 'Finding', text: 'A symptom: this metric changed, with the evidence. Not a diagnosis.', who: 'Ops Signals · Findings' },
  { step: 'case', title: 'Case', text: 'A problem: a finding you decided is real and are working on.', who: 'You · Cases' },
  { step: 'memory', title: 'Memory', text: 'What a fixed case taught you, found again next time.', who: 'Ops Signals · Recurring problems' },
];

export interface GlossaryTerm {
  term: string;
  /** The heading in docs/glossary.md this is shortened from. */
  heading: string;
  text: string;
}

const TERMS = {
  evidence: { term: 'Evidence badge', heading: 'Evidence badge', text: 'How much to trust a finding: Strong (two checks agree), Moderate (one check), Data problem (the metric stopped or froze), Context only.' },
  attention: { term: 'Needs attention', heading: 'Needs attention and Context only', text: "Worth a look now. Context only is background for when you're already investigating." },
  real: { term: 'Was this real?', heading: 'Was this real?', text: "Your team's answer: Real problem, Not a problem, or Expected change (real but planned, like a deploy)." },
  seenBefore: { term: 'Seen before', heading: 'Seen before', text: 'Past cases look like this one; shows the closest and what fixed it.' },
  findingVsAlert: { term: 'Finding vs alert', heading: 'Finding vs alert', text: 'An alert is what your own alert rule paged for. A finding is something unusual Ops Signals noticed, maybe with no rule.' },
  findingVsCase: { term: 'Finding vs case', heading: 'Finding vs case', text: 'A finding is a symptom Ops Signals noticed; a case is a problem you decided to work on. Many findings never become cases.' },
  rootCause: { term: 'Root cause', heading: 'Root cause', text: 'Why the problem happened, recorded on the case.' },
  resolution: { term: 'Resolution', heading: 'Resolution', text: 'What fixed it. Seen before shows it the next time something similar happens.' },
  fixDidntHold: { term: "Fix didn't hold", heading: "Fix didn't hold", text: 'The same problem came back on the same service within 30 days of a fix; names the old fix.' },
  combined: { term: 'Combined pattern', heading: 'Combined pattern', text: 'A problem that only shows when several metrics are looked at together.' },
  pattern: { term: 'Behavior pattern', heading: 'Behavior pattern', text: 'The rule a combined pattern matched: built in, mined from your data, or written by an admin.' },
  signal: { term: 'Signal', heading: 'Signal', text: "One analyzer's raw output on one metric. Patterns combine signals from several metrics." },
  memory: { term: 'Operational memory', heading: 'Operational memory', text: 'Past cases saved so they can be searched by similarity. A match means "looks alike", not "same cause".' },
  recurring: { term: 'Recurring problem', heading: 'Recurring problem', text: 'A group of past cases that keep coming back, with the causes found and what to do next.' },
  imported: { term: 'Imported incident', heading: 'Imported incident', text: 'A past incident or postmortem you loaded in, so memory can match against it from day one.' },
} satisfies Record<string, GlossaryTerm>;

export const PAGE_GLOSSARY: Record<GlossaryPage, { step: ChainStep | null; terms: GlossaryTerm[] }> = {
  findings: { step: 'finding', terms: [TERMS.evidence, TERMS.attention, TERMS.real, TERMS.seenBefore, TERMS.findingVsAlert] },
  cases: { step: 'case', terms: [TERMS.findingVsCase, TERMS.rootCause, TERMS.resolution, TERMS.fixDidntHold, TERMS.seenBefore] },
  behavior: { step: 'finding', terms: [TERMS.combined, TERMS.pattern, TERMS.signal] },
  recurring: { step: 'memory', terms: [TERMS.memory, TERMS.recurring, TERMS.fixDidntHold, TERMS.imported] },
  // The plugin's Overview holds findings, cases, patterns and past cases on one page.
  overview: { step: null, terms: [TERMS.findingVsCase, TERMS.evidence, TERMS.combined, TERMS.seenBefore, TERMS.fixDidntHold] },
};

export const ALL_GLOSSARY_TERMS: GlossaryTerm[] = Object.values(TERMS);
