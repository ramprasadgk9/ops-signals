// What ran on a series and why, built from a run's router decisions and analyzer execution
// records. Shared by the web UI's Router Decisions panel and the Grafana plugin so the two read
// the same story. The backend records why each analyzer ran or didn't (`run_reason`, see
// intelligence/analyzer_selection.py RUN_REASON_TEXT); runs saved before that existed fall back
// to the router's own wording.

export type RunDecision = {
  analyzer_id?: string;
  display_name?: string;
  recommendation?: string;
  final_score?: number;
  routing_reason?: string;
  explanation?: string;
  reasons?: string[];
  warnings?: string[];
  parameters_tested?: { detected_profiles?: string[] } | null;
};

export type RunExecution = {
  router_analyzer_id?: string;
  display_name?: string;
  recommendation?: string;
  selected?: boolean;
  executed_pipeline_analyzer_ids?: string[];
  failed_pipeline_analyzer_ids?: string[];
  execution_status?: string;
  execution_reason?: string | null;
  run_reason?: string | null;
  shapes?: string[];
  missing_library?: string | null;
  in_finding?: boolean | null;
  description?: string | null;
};

export type RanTone = 'pick' | 'cover' | 'always' | 'failed';

export type RanAnalyzer = {
  id: string;
  name: string;
  label: string;
  tone: RanTone;
  reason: string;
  /** "In the finding" / "No finding"; null when the run didn't record it. */
  outcome: string | null;
  inFinding: boolean | null;
  /** What the analyzer looks for, shown as a tip; null for runs saved before descriptions. */
  description: string | null;
};

export type MissingLibrary = { id: string; name: string; library: string };

export type ScoredAnalyzer = {
  id: string;
  name: string;
  score: number | null;
  rating: string;
  shapes: string[];
  outcome: string;
  ran: boolean;
  description: string | null;
};

export type AnalyzerRunView = {
  ran: RanAnalyzer[];
  missingLibraries: MissingLibrary[];
  scored: ScoredAnalyzer[];
  notBuiltIn: { id: string; name: string }[];
  detectedShapes: string[];
};

const SHAPE_GROUPS: Record<string, string[]> = {
  spike: ['anomaly', 'outlier', 'spike'],
  baseline: ['baseline_shift', 'regime_change'],
  seasonal: ['seasonal', 'repeating_pattern'],
  trend: ['trend'],
};

const SHAPE_NAMES: Record<string, string> = {
  spike: 'spikes',
  baseline: 'baseline shift',
  seasonal: 'seasonal pattern',
  trend: 'trend',
};

const RAN_LABELS: Record<string, { label: string; tone: RanTone; order: number }> = {
  router_pick: { label: 'Router pick', tone: 'pick', order: 0 },
  chosen_in_settings: { label: 'Chosen in settings', tone: 'pick', order: 0 },
  covers_shape: { label: 'Covers a shape', tone: 'cover', order: 1 },
  spike_fallback: { label: 'Covers spikes', tone: 'cover', order: 1 },
  always_run: { label: 'Runs on every series', tone: 'always', order: 2 },
  runs_all: { label: 'Runs every analyzer', tone: 'always', order: 2 },
};

const SKIP_OUTCOMES: Record<string, string> = {
  library_missing: 'Library not installed',
  turned_off: 'Turned off',
  rejected: 'Ruled out',
  not_selected: 'Not chosen',
  router_failed: "Couldn't score",
};

export function ratingLabel(recommendation: string | undefined): string {
  const value = String(recommendation ?? '').toUpperCase();
  if (value === 'RECOMMENDED') return 'Recommended';
  if (value === 'OPTIONAL') return 'Optional';
  if (value === 'REJECTED') return 'Ruled out';
  if (value === 'UNROUTED') return 'Not scored';
  return 'Not recommended';
}

export function shapeNames(groups: string[]): string[] {
  return groups.filter((group) => SHAPE_NAMES[group]).map((group) => SHAPE_NAMES[group]);
}

function detectedShapeGroups(decisions: RunDecision[]): string[] {
  const detected = new Set(decisions.flatMap((decision) => decision.parameters_tested?.detected_profiles ?? []));
  return Object.entries(SHAPE_GROUPS)
    .filter(([, profiles]) => profiles.some((profile) => detected.has(profile)))
    .map(([group]) => group);
}

function routerWording(decision: RunDecision | undefined): string {
  if (!decision) return '';
  return (
    decision.routing_reason ||
    decision.explanation ||
    [...(decision.reasons ?? []), ...(decision.warnings ?? [])].slice(0, 2).join(' ') ||
    ''
  );
}

function ranLabel(execution: RunExecution): { label: string; tone: RanTone; order: number } {
  const known = RAN_LABELS[execution.run_reason ?? ''];
  if (!known) return { label: 'Ran', tone: 'pick', order: 0 };
  if (execution.run_reason === 'covers_shape') {
    const shapes = shapeNames(execution.shapes ?? []);
    return { ...known, label: shapes.length ? `Covers ${shapes.join(' and ')}` : known.label };
  }
  return known;
}

function findingOutcome(inFinding: boolean | null | undefined, findingCount: number | null): string | null {
  if (inFinding === true) return findingCount === 1 ? 'In the finding' : 'In a finding';
  if (inFinding === false) return 'No finding';
  return null;
}

function scoredOutcome(execution: RunExecution | undefined): string {
  if (!execution) return 'Not run';
  if (execution.execution_status === 'failed') return 'Failed';
  if (execution.execution_status === 'completed') {
    const reason = execution.run_reason ?? '';
    if (reason === 'covers_shape' || reason === 'spike_fallback') return 'Ran to cover a shape';
    if (reason === 'always_run') return 'Ran (every series)';
    return 'Ran';
  }
  return SKIP_OUTCOMES[execution.run_reason ?? ''] ?? execution.execution_reason ?? 'Not run';
}

/**
 * `findingCount` is the run's number of findings, used only to word "In the finding" vs "In a
 * finding"; pass null when unknown.
 */
export function buildAnalyzerRunView(
  decisions: RunDecision[],
  executions: RunExecution[],
  findingCount: number | null = null,
): AnalyzerRunView {
  const decisionById = new Map(decisions.filter((item) => item.analyzer_id).map((item) => [item.analyzer_id as string, item]));
  const executionById = new Map(
    executions.filter((item) => item.router_analyzer_id).map((item) => [item.router_analyzer_id as string, item]),
  );

  const ranRows: (RanAnalyzer & { order: number; score: number })[] = [];
  const missingLibraries: MissingLibrary[] = [];
  const notBuiltIn: { id: string; name: string }[] = [];
  // Runs saved before the backend fix also list an aliased analyzer (trend_regression ran as
  // trend) a second time as unrouted; that copy is dropped here.
  const reportedByRouter = new Set(
    executions
      .filter((item) => item.recommendation !== 'UNROUTED')
      .flatMap((item) => [...(item.executed_pipeline_analyzer_ids ?? []), ...(item.failed_pipeline_analyzer_ids ?? [])]),
  );
  for (const execution of executions) {
    const id = execution.router_analyzer_id;
    if (!id) continue;
    if (execution.recommendation === 'UNROUTED' && reportedByRouter.has(id)) continue;
    const decision = decisionById.get(id);
    const name = execution.display_name || decision?.display_name || id;
    const status = execution.execution_status;
    if (status === 'completed' || status === 'failed') {
      const failed = status === 'failed';
      const label = failed ? { label: 'Failed', tone: 'failed' as const, order: 3 } : ranLabel(execution);
      ranRows.push({
        id,
        name,
        label: label.label,
        tone: label.tone,
        order: label.order,
        score: decision?.final_score ?? -1,
        reason: execution.execution_reason || routerWording(decision),
        outcome: failed ? null : findingOutcome(execution.in_finding, findingCount),
        inFinding: failed ? null : execution.in_finding ?? null,
        description: execution.description ?? null,
      });
    } else if (execution.run_reason === 'library_missing') {
      missingLibraries.push({ id, name, library: execution.missing_library || id });
    } else if (execution.run_reason === 'not_built_in') {
      notBuiltIn.push({ id, name });
    }
  }
  ranRows.sort((a, b) => a.order - b.order || b.score - a.score);

  const notBuiltInIds = new Set(notBuiltIn.map((item) => item.id));
  const scored: ScoredAnalyzer[] = decisions
    .filter((decision) => decision.analyzer_id && !notBuiltInIds.has(decision.analyzer_id))
    .map((decision) => {
      const id = decision.analyzer_id as string;
      const execution = executionById.get(id);
      const status = execution?.execution_status;
      return {
        id,
        name: decision.display_name || id,
        score: typeof decision.final_score === 'number' ? decision.final_score : null,
        rating: ratingLabel(decision.recommendation),
        shapes: shapeNames(execution?.shapes ?? []),
        outcome: scoredOutcome(execution),
        ran: status === 'completed' || status === 'failed',
        description: execution?.description ?? null,
      };
    })
    .sort((a, b) => (b.score ?? -1) - (a.score ?? -1));

  return {
    ran: ranRows.map(({ order: _order, score: _score, ...row }) => row),
    missingLibraries,
    scored,
    notBuiltIn,
    detectedShapes: shapeNames(detectedShapeGroups(decisions)),
  };
}

/** One analyzer's story for the plugin assistant: whether it ran, and why or why not. */
export function explainAnalyzerRun(analyzerId: string, decisions: RunDecision[], executions: RunExecution[]): string {
  const decision = decisions.find((item) => item.analyzer_id === analyzerId);
  const execution = executions.find((item) => item.router_analyzer_id === analyzerId);
  const name = execution?.display_name || decision?.display_name || analyzerId;
  const scoreText =
    decision && typeof decision.final_score === 'number'
      ? ` The router rated it ${ratingLabel(decision.recommendation).toLowerCase()} (score ${decision.final_score.toFixed(2)}).`
      : '';
  if (!execution) {
    return decision ? `${name} was scored by the router but has no run record for this run.${scoreText}` : `${name} wasn't part of this run.`;
  }
  const status = execution.execution_status;
  if (status === 'failed') return `${name} was set to run but failed: ${execution.execution_reason ?? 'no error recorded'}.${scoreText}`;
  if (status === 'completed') {
    const why = execution.execution_reason || ranLabel(execution).label;
    const found =
      execution.in_finding === true ? ' Its results are part of a finding.' : execution.in_finding === false ? ' It found nothing that became a finding.' : '';
    return `${name} ran. ${why}${found}${scoreText}`;
  }
  switch (execution.run_reason) {
    case 'not_built_in':
      return `${name} can't run: it's in the router's catalog but not built into Ops Signals yet, so its score is for reference only.${scoreText}`;
    case 'library_missing':
      return `${name} didn't run because the ${execution.missing_library ?? analyzerId} library isn't installed where the backend runs.${scoreText}`;
    case 'turned_off':
      return `${name} didn't run because it's turned off in the analyzer settings.${scoreText}`;
    case 'rejected':
      return `${name} didn't run: the router ruled it out for this series. ${routerWording(decision)}`.trim();
    default:
      return `${name} didn't run. ${execution.execution_reason ?? 'It was not chosen for this run.'}${scoreText}`;
  }
}

/** The whole run in one paragraph for the plugin assistant. */
export function summarizeAnalyzerRuns(view: AnalyzerRunView): string {
  const ran = view.ran.length
    ? `Ran: ${view.ran.map((row) => `${row.name} (${row.label.toLowerCase()})`).join(', ')}.`
    : 'No analyzer ran on this series.';
  const missing = view.missingLibraries.length
    ? ` Couldn't run because a library isn't installed: ${view.missingLibraries.map((item) => item.name).join(', ')}.`
    : '';
  const notBuiltIn = view.notBuiltIn.length
    ? ` Scored for reference but not built into Ops Signals: ${view.notBuiltIn.map((item) => item.name).join(', ')}.`
    : '';
  const shapes = view.detectedShapes.length ? ` Shapes detected: ${view.detectedShapes.join(', ')}.` : '';
  return `${ran}${shapes}${missing}${notBuiltIn}`;
}
