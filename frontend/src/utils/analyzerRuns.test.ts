import { describe, expect, it } from 'vitest';
import { buildAnalyzerRunView, explainAnalyzerRun, summarizeAnalyzerRuns, type RunDecision, type RunExecution } from './analyzerRuns';

// The run from the Router Decisions screenshot: a baseline shift with a trend and spikes.
const detected = { detected_profiles: ['baseline_shift', 'regime_change', 'trend', 'spike', 'outlier'] };
const decisions: RunDecision[] = [
  { analyzer_id: 'ruptures', display_name: 'Ruptures', recommendation: 'RECOMMENDED', final_score: 1, parameters_tested: detected },
  { analyzer_id: 'pyod', display_name: 'PyOD', recommendation: 'RECOMMENDED', final_score: 1 },
  { analyzer_id: 'adtk', display_name: 'ADTK', recommendation: 'RECOMMENDED', final_score: 0.96 },
  { analyzer_id: 'trend_regression', display_name: 'Trend Regression', recommendation: 'RECOMMENDED', final_score: 0.9 },
  { analyzer_id: 'pyod_outlier', display_name: 'PyOD Outlier Detection', recommendation: 'OPTIONAL', final_score: 0.78 },
  { analyzer_id: 'stumpy', display_name: 'STUMPY', recommendation: 'NOT_RECOMMENDED', final_score: 0.42, routing_reason: 'Profiles did not match.' },
  { analyzer_id: 'data_health', display_name: 'Data Health', recommendation: 'NOT_RECOMMENDED', final_score: 0.3 },
  { analyzer_id: 'prophet', display_name: 'Prophet', recommendation: 'REJECTED', final_score: 0, routing_reason: 'Library not installed.' },
];
const ran = (id: string, run_reason: string, in_finding: boolean, extra: Partial<RunExecution> = {}): RunExecution => ({
  router_analyzer_id: id,
  execution_status: 'completed',
  executed_pipeline_analyzer_ids: [id],
  run_reason,
  in_finding,
  ...extra,
});
const executions: RunExecution[] = [
  ran('ruptures', 'router_pick', true, { execution_reason: 'Picked by the router for this series.' }),
  { router_analyzer_id: 'pyod', execution_status: 'skipped', run_reason: 'not_built_in' },
  { router_analyzer_id: 'adtk', execution_status: 'skipped', run_reason: 'not_built_in' },
  ran('trend_regression', 'router_pick', false, { display_name: 'Trend Regression' }),
  ran('pyod_outlier', 'covers_shape', false, { shapes: ['spike'], execution_reason: 'Ran to cover the spikes the router detected.' }),
  ran('stumpy', 'always_run', false, { execution_reason: 'Runs on every series.' }),
  ran('data_health', 'always_run', false),
  { router_analyzer_id: 'prophet', execution_status: 'skipped', run_reason: 'library_missing', missing_library: 'prophet' },
];

describe('buildAnalyzerRunView', () => {
  const view = buildAnalyzerRunView(decisions, executions, 1);

  it('lists what ran, router picks first, with a reason label each', () => {
    expect(view.ran.map((row) => [row.id, row.label])).toEqual([
      ['ruptures', 'Router pick'],
      ['trend_regression', 'Router pick'],
      ['pyod_outlier', 'Covers spikes'],
      ['stumpy', 'Runs on every series'],
      ['data_health', 'Runs on every series'],
    ]);
  });

  it("uses the run's reason, not the router's 'did not match' wording, for an analyzer that ran", () => {
    expect(view.ran.find((row) => row.id === 'stumpy')?.reason).toBe('Runs on every series.');
  });

  it('says which analyzers fed the finding', () => {
    expect(view.ran.map((row) => row.outcome)).toEqual(['In the finding', 'No finding', 'No finding', 'No finding', 'No finding']);
    expect(buildAnalyzerRunView(decisions, executions, 2).ran[0].outcome).toBe('In a finding');
  });

  it('keeps catalog-only analyzers out of the scored list', () => {
    expect(view.notBuiltIn.map((item) => item.id)).toEqual(['pyod', 'adtk']);
    expect(view.scored.map((row) => row.id)).not.toContain('pyod');
    expect(view.scored.map((row) => row.id)).not.toContain('adtk');
  });

  it('offers a fix only for a missing library', () => {
    expect(view.missingLibraries).toEqual([{ id: 'prophet', name: 'Prophet', library: 'prophet' }]);
  });

  it('gives each scored analyzer its rating and outcome', () => {
    const byId = Object.fromEntries(view.scored.map((row) => [row.id, row]));
    expect(byId.stumpy).toMatchObject({ rating: 'Not recommended', outcome: 'Ran (every series)', ran: true });
    expect(byId.pyod_outlier).toMatchObject({ rating: 'Optional', outcome: 'Ran to cover a shape', shapes: ['spikes'] });
    expect(byId.prophet).toMatchObject({ rating: 'Ruled out', outcome: 'Library not installed', ran: false });
  });

  it('names the detected shapes', () => {
    expect(view.detectedShapes).toEqual(['spikes', 'baseline shift', 'trend']);
  });

  it("falls back to the router's wording for runs saved before reasons were recorded", () => {
    const legacy = buildAnalyzerRunView(
      [{ analyzer_id: 'stumpy', display_name: 'STUMPY', recommendation: 'RECOMMENDED', final_score: 0.9, routing_reason: 'Repeating pattern.' }],
      [{ router_analyzer_id: 'stumpy', execution_status: 'completed', execution_reason: null }],
    );
    expect(legacy.ran).toEqual([
      { id: 'stumpy', name: 'STUMPY', label: 'Ran', tone: 'pick', reason: 'Repeating pattern.', outcome: null, inFinding: null },
    ]);
  });

  it('drops the unrouted copy of an aliased analyzer that older runs recorded', () => {
    const older = buildAnalyzerRunView(
      [{ analyzer_id: 'trend_regression', display_name: 'Trend Regression', recommendation: 'RECOMMENDED', final_score: 0.9 }],
      [
        { router_analyzer_id: 'trend_regression', recommendation: 'RECOMMENDED', execution_status: 'completed', executed_pipeline_analyzer_ids: ['trend'] },
        { router_analyzer_id: 'trend', recommendation: 'UNROUTED', execution_status: 'completed', executed_pipeline_analyzer_ids: ['trend'] },
      ],
    );
    expect(older.ran.map((row) => row.id)).toEqual(['trend_regression']);
  });

  it('marks a failed analyzer as failed with its error', () => {
    const failed = buildAnalyzerRunView(decisions, [
      { router_analyzer_id: 'ruptures', execution_status: 'failed', execution_reason: 'ruptures: boom', run_reason: 'router_pick' },
    ]);
    expect(failed.ran[0]).toMatchObject({ label: 'Failed', tone: 'failed', reason: 'ruptures: boom', outcome: null });
  });
});

describe('explainAnalyzerRun', () => {
  it('explains an always-run analyzer that the router rated low', () => {
    const answer = explainAnalyzerRun('stumpy', decisions, executions);
    expect(answer).toContain('STUMPY ran. Runs on every series.');
    expect(answer).toContain('not recommended (score 0.42)');
  });

  it('says a catalog-only analyzer cannot run instead of tying it to another analyzer', () => {
    expect(explainAnalyzerRun('pyod', decisions, executions)).toContain("can't run: it's in the router's catalog but not built into Ops Signals yet");
  });

  it('names the missing library', () => {
    expect(explainAnalyzerRun('prophet', decisions, executions)).toContain('the prophet library isn\'t installed');
  });

  it('says whether the analyzer fed a finding', () => {
    expect(explainAnalyzerRun('ruptures', decisions, executions)).toContain('Its results are part of a finding.');
  });
});

describe('summarizeAnalyzerRuns', () => {
  it('summarizes what ran, what is missing a library and what is catalog-only', () => {
    const summary = summarizeAnalyzerRuns(buildAnalyzerRunView(decisions, executions, 1));
    expect(summary).toContain('Ran: Ruptures (router pick), Trend Regression (router pick), PyOD Outlier Detection (covers spikes), STUMPY (runs on every series), Data Health (runs on every series).');
    expect(summary).toContain("Couldn't run because a library isn't installed: Prophet.");
    expect(summary).toContain('Scored for reference but not built into Ops Signals: PyOD, ADTK.');
  });
});
