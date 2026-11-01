import { test, expect } from '@playwright/test';
import { analyzerFixtures } from '../../shared/fixtures';
import { loadFixtureAsSeedPoints } from '../../shared/fixtures';
import { makeRunId, seedNormalizedPoints, cleanupRun } from '../../shared/db';

/**
 * Data source = an analyzed metric picked on "Which analyzer fits my metric?"
 * (AnalyzerRecommendationPage). The metric list reads recent analysis runs (one row per run, from
 * the analysis_runs table). We seed a run and its ops_normalized_timeseries_points directly with
 * the same fixture shapes used by the CSV-upload spec, rather than waiting on real Prometheus
 * scrape history.
 *
 * This is a router-scoring preview (POST /api/metric-analyzer-recommendations/evaluate), not a
 * pipeline execution. The page groups the router's ratings into three columns: recommended ->
 * Good fit, optional/conditional -> Can help, anything else (not_recommended, rejected) -> Not a
 * fit. Router candidates that aren't built into Ops Signals are listed apart, under the columns.
 */

// The router's scoring id and the runtime/pipeline analyzer id it executes as aren't always the
// same string (see docs/analyzer-recommendation.md and benchmark/router_benchmark.py's
// ROUTER_TO_PIPELINE_ANALYZER_ID) - the page uses the pipeline id via service.py's
// _public_analyzer_id(), while expectedOutcomes below is keyed by router id.
const ROUTER_TO_PIPELINE_ANALYZER_ID: Record<string, string> = { trend_regression: 'trend' };

const COLUMN: Record<string, string> = { recommended: 'Good fit', optional: 'Can help', conditional: 'Can help' };
const columnFor = (outcome: string) => COLUMN[outcome] ?? 'Not a fit';
const FIT: Record<string, string> = { 'Good fit': 'good', 'Can help': 'can_help', 'Not a fit': 'not_a_fit' };

// Router candidates with no pipeline analyzer behind them (run_reason "not_built_in").
const NOT_BUILT_IN = new Set(['river', 'kats', 'darts', 'alibi_detect', 'adtk', 'pyod']);

for (const key of ['ruptures', 'trend', 'stumpy', 'pyodOutlier', 'mixed'] as const) {
  const fixture = analyzerFixtures[key];

  test(`seeded sample for ${fixture.file} lands in the documented columns`, async ({ page }) => {
    const runId = makeRunId(`seeded-${key}`);
    await seedNormalizedPoints({
      runId,
      service: fixture.service,
      metricName: fixture.metricName,
      points: loadFixtureAsSeedPoints(fixture),
    });

    try {
      await page.goto('/analyzer-recommendation');
      // Every fixture's metric is cpu_usage; the option also names its service.
      await page.getByLabel('Metric').fill(fixture.service);
      await page.getByRole('option', { name: new RegExp(`cpu_usage.*${fixture.service}`) }).click();
      await page.getByRole('button', { name: 'Find the right analyzer' }).click();
      await expect(page.getByRole('region', { name: 'Good fit' })).toBeVisible({ timeout: 30_000 });

      for (const [analyzerId, outcome] of Object.entries(fixture.expectedOutcomes)) {
        const pipelineAnalyzerId = ROUTER_TO_PIPELINE_ANALYZER_ID[analyzerId] ?? analyzerId;
        if (NOT_BUILT_IN.has(pipelineAnalyzerId)) {
          await expect(page.getByTestId(`not-built-in-${pipelineAnalyzerId}`)).toHaveAttribute('data-fit', FIT[columnFor(outcome)]);
          continue;
        }
        await expect(page.getByRole('region', { name: columnFor(outcome) }).getByTestId(`fit-${pipelineAnalyzerId}`)).toBeVisible();
      }
    } finally {
      await cleanupRun({ runId });
    }
  });
}

test('a link with service and metric opens that metric ready to check', async ({ page }) => {
  const fixture = analyzerFixtures.trend;
  const runId = makeRunId('seeded-link');
  await seedNormalizedPoints({ runId, service: fixture.service, metricName: fixture.metricName, points: loadFixtureAsSeedPoints(fixture) });

  try {
    await page.goto(`/analyzer-recommendation?service=${fixture.service}&metric=${fixture.metricName}`);
    await expect(page.getByText(new RegExp(`Uses the latest analysis of ${fixture.metricName} on ${fixture.service}`))).toBeVisible();
    await page.getByRole('button', { name: 'Find the right analyzer' }).click();
    const trend = page.getByRole('region', { name: 'Good fit' }).getByTestId('fit-trend');
    await expect(trend).toBeVisible({ timeout: 30_000 });
    await expect(trend.getByRole('link', { name: 'Try in Labs' })).toHaveAttribute('href', '/experiments/trend-lab');
    await expect(page.getByRole('link', { name: `See what runs on ${fixture.service}` })).toBeVisible();
    // Registered analyzers the router never scores are named under the columns.
    await expect(page.getByTestId('not-scored').getByRole('link', { name: 'Seasonal Anomaly' })).toBeVisible();
  } finally {
    await cleanupRun({ runId });
  }
});
