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
 * KNOWN APP BUG (confirmed against a live run, not a test/selector issue): selecting a sample from
 * "Select Existing Sample" never actually gets sent to the backend. The onChange handler
 * (AnalyzerRecommendationPage.tsx ~420-432) copies metric_name into context and sets
 * `sample_id: undefined` — it never attaches the sample's service/analysis_run_id anywhere the
 * chatMutation payload reads from (that payload only sends conversation_id, message,
 * metric_context, options). So clicking "Evaluate with Sample" produces the same request as a
 * plain preliminary evaluation regardless of which sample is selected — confirmed live: the
 * response still comes back `recommendation_mode: "preliminary"` with the "select a representative
 * historical sample" warning still showing, even with a real 120-point sample selected.
 * Cross-checked: POST /api/metric-analyzer-recommendations/evaluate with an explicit
 * analysis_run_id DOES return real evidence-based recommendations, so the backend logic itself is
 * fine — this is a frontend wiring gap. Also surfaced along the way: real recommendation values
 * include at least a 4th value, "rejected", which this page's 3-bucket rendering
 * (recommended/conditional/not_recommended) doesn't account for.
 *
 * Left failing (test.fixme) rather than rewritten around the bug or silently deleted, so the
 * suite stays honest about what's broken. Once the sample-selection wiring is fixed, remove the
 * test.fixme() call below.
 */

for (const key of ['ruptures', 'trend', 'stumpy', 'pyodOutlier', 'mixed'] as const) {
  const fixture = analyzerFixtures[key];

  test(`seeded sample for ${fixture.file} evaluates to the documented router outcomes`, async ({ page }) => {
    test.fixme(true, 'Select Existing Sample does not forward the sample identity to the backend — see file header.');
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

      for (const [analyzerId, outcome] of Object.entries(fixture.expectedOutcomes)) {
        if (outcome === 'not_recommended') {
          await expect(page.getByText('not recommended')).toBeVisible();
        } else {
          await expect(page.getByText(outcome, { exact: true }).first()).toBeVisible();
        }
        await expect(page.getByRole('button', { name: `Copy snippet for ${analyzerId}` })).toBeVisible();
      }
    } finally {
      await cleanupRun({ runId });
    }
  });
}
