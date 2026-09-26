import { test, expect } from '@playwright/test';
import { analyzerFixtures } from '../../shared/fixtures';
import { loadFixtureAsSeedPoints } from '../../shared/fixtures';
import { makeRunId, seedNormalizedPoints, cleanupRun } from '../../shared/db';

/**
 * Data source = a pre-existing sample selected via AnalyzerRecommendationPage's
 * "Select Existing Sample" dropdown, which lists distinct (service, metric_name, analysis_run_id)
 * rows out of ops_normalized_timeseries_points. We seed that table directly with the same fixture
 * shapes used by the CSV-upload spec, rather than waiting on real Prometheus scrape history —
 * see the suite discussion on why live-Prometheus outcome assertions are DB-seeded, not scrape-timed.
 *
 * This flow is a router-scoring preview (POST /api/metric-analyzer-recommendations/chat), not a
 * pipeline execution, so it only ever buckets into recommended / conditional / not_recommended —
 * there is no "unavailable" state here (that's execution-time only; see csv-upload-routing-outcomes.spec.ts).
 *
 * Formerly test.fixme() for the app bug tracked as issue #15: the "Select Existing Sample"
 * onChange handler set `sample_id: undefined` and left `provider` at its default 'prometheus'
 * (AnalyzerRecommendationPage.tsx ~420-436), so the backend's service-name match against the
 * selected sample always failed and every evaluation silently fell back to `preliminary` mode
 * regardless of which sample was picked. Fixed by setting `sample_id` and unconditionally
 * overwriting `provider` with the selected sample's own service on selection.
 */

// The router's scoring id and the runtime/pipeline analyzer id it executes as aren't always the
// same string (see docs/16-analyzer-recommendation.md and benchmark/router_benchmark.py's
// ROUTER_TO_PIPELINE_ANALYZER_ID) - "Copy snippet for X" on this page renders the pipeline id via
// service.py's _public_analyzer_id(), while expectedOutcomes below is keyed by router id.
const ROUTER_TO_PIPELINE_ANALYZER_ID: Record<string, string> = { trend_regression: 'trend' };

for (const key of ['ruptures', 'trend', 'stumpy', 'pyodOutlier', 'mixed'] as const) {
  const fixture = analyzerFixtures[key];

  test(`seeded sample for ${fixture.file} evaluates to the documented router outcomes`, async ({ page }) => {
    const runId = makeRunId(`seeded-${key}`);
    await seedNormalizedPoints({
      runId,
      service: fixture.service,
      metricName: fixture.metricName,
      points: loadFixtureAsSeedPoints(fixture),
    });

    try {
      await page.goto('/analyzer-recommendation');
      // Templates only fill operational_purpose/use_cases/operational_questions, not Metric
      // Name/Description (confirmed against a live run) — fill those directly. Selecting the
      // sample below overwrites Metric Name to match the sample's metric_name anyway.
      await page.getByLabel('Metric Name').fill(fixture.metricName);
      await page.getByLabel('Metric Description').fill('Integration suite seeded sample for router evaluation.');
      await page.getByRole('button', { name: 'CPU Template' }).click();

      // The MUI Select's `label` prop doesn't wire up aria-labelledby here, so the combobox has
      // no accessible name at all (confirmed against a live run) — anchor off the InputLabel's
      // visible text and step to its sibling instead of getByLabel.
      const sampleSelect = page
        .getByText('Select Existing Sample', { exact: true })
        .locator('xpath=following-sibling::*[1]')
        .getByRole('combobox');
      await sampleSelect.click();
      await page.getByRole('option', { name: new RegExp(`${fixture.service} / ${fixture.metricName} \\(${runId}\\)`) }).click();

      await page.getByRole('button', { name: 'Evaluate with Sample' }).click();
      await expect(page.getByText('Recommendation Results')).toBeVisible({ timeout: 30_000 });

      // Each analyzer's result card holds its snippet button and a chip with its recommendation.
      // Checking the chip inside that one card, not text anywhere on the page: bucket headings
      // ("recommended", "not recommended") used to satisfy page-wide checks for any analyzer.
      for (const [analyzerId, outcome] of Object.entries(fixture.expectedOutcomes)) {
        const pipelineAnalyzerId = ROUTER_TO_PIPELINE_ANALYZER_ID[analyzerId] ?? analyzerId;
        const snippetButton = page.getByRole('button', { name: `Copy snippet for ${pipelineAnalyzerId}` });
        await expect(snippetButton).toBeVisible();
        // Innermost element containing the button (ancestors come first in document order).
        const card = page.locator('div').filter({ has: snippetButton }).last();
        await expect(card.getByText(outcome, { exact: true })).toBeVisible();
      }
    } finally {
      await cleanupRun({ runId });
    }
  });
}
