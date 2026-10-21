import { test, expect } from '@playwright/test';
import { analyzerFixtures, writeUploadableCsv } from '../../shared/fixtures';
import { seedUnmappedCustomAnalyzer, deleteCustomAnalyzerDraft } from '../../shared/customAnalyzer';
import { env } from '../../shared/env';

/**
 * Data source = CSV upload, driven through the real ValidateDataPage file input and pipeline run
 * (not mocked). The fixture CSVs use `timestamp,cpu_usage` columns (built for
 * dev/mock_prometheus_target.py's Prometheus-scrape replay), which the upload endpoint rejects —
 * writeUploadableCsv() reshapes them to `timestamp,metric,value,service` first.
 *
 * Expected outcomes are captured from live runs (2026-09-08, fixture 04 re-captured 2026-10-20),
 * not from sample_data/ops_signals_test_series/README.md's "Expected routing behavior" table, so
 * this suite catches real regressions from today's baseline. See analyzerFixtures.pyodOutlier's
 * comment in shared/fixtures.ts for fixture 04.
 */

async function openCsvTab(page: import('@playwright/test').Page) {
  await page.goto('/validate-data');
  await page.getByRole('tab', { name: 'CSV Upload' }).click();
}

async function uploadAndRun(page: import('@playwright/test').Page, csvPath: string, service: string, metricName: string) {
  await page.getByLabel('Service').fill(service);
  await page.getByLabel('Metric').fill(metricName);
  await page.locator('input[type="file"]').setInputFiles(csvPath);
  await page.getByRole('button', { name: 'Validate Data' }).click();
  // "Router Decisions" heading is always present (even pre-run, showing "No router decisions
  // returned yet.") — confirmed against a live run. Wait for that placeholder text to go away
  // instead of just the heading, so this actually waits for the run to complete.
  await expect(page.getByRole('heading', { name: 'Router Decisions' })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText('No router decisions returned yet.')).toBeHidden({ timeout: 30_000 });
}

// Router candidates with no pipeline analyzer behind them: the panel lists these apart from the
// scoring table, under "not built into Ops Signals yet" (run_reason "not_built_in").
const NOT_BUILT_IN = new Set(['river', 'kats', 'darts', 'alibi_detect', 'adtk', 'pyod']);

async function openRouterScoring(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: /How the router scored this series/ }).click();
}

async function expectRouterOutcome(page: import('@playwright/test').Page, analyzerId: string, rating: string) {
  if (NOT_BUILT_IN.has(analyzerId)) {
    await expect(page.getByTestId(`router-not-built-in-${analyzerId}`)).toBeVisible();
    return;
  }
  await expect(page.getByTestId(`router-rating-${analyzerId}`)).toHaveText(rating);
}

for (const key of ['ruptures', 'trend', 'stumpy', 'pyodOutlier', 'mixed'] as const) {
  const fixture = analyzerFixtures[key];

  test(`CSV upload of ${fixture.file} routes analyzers as observed live`, async ({ page }) => {
    const uploadPath = writeUploadableCsv(fixture);
    await openCsvTab(page);
    await uploadAndRun(page, uploadPath, fixture.service, fixture.metricName);

    await openRouterScoring(page);
    for (const [analyzerId, rating] of Object.entries(fixture.csvRouterOutcomes)) {
      await expectRouterOutcome(page, analyzerId, rating);
    }
  });
}

test('CSV upload with a router-recommended but runtime-unmapped custom analyzer reports it unavailable', async ({ page }) => {
  test.fixme(
    true,
    'Confirmed live: a promoted custom analyzer with runtime_mapping="not_implemented" never appears in ' +
      'analyzer_routing at all (not even as excluded/rejected), even after a fresh backend restart to rule out ' +
      'stale in-memory registry state. So there is nothing to assert "unavailable" on with the current backend ' +
      'behavior — either custom analyzers are excluded earlier in the CSV-validate flow for a reason not yet ' +
      'traced, or the "unavailable" execution-status concept (docs/analyzer-recommendation.md) applies to a different ' +
      'flow than csv-validate. Needs product/eng input before this can be written meaningfully.'
  );

  const analyzerId = 'integration_suite_unmapped';
  const { draftId } = await seedUnmappedCustomAnalyzer(env.webUiBackendUrl, analyzerId);

  try {
    const fixture = analyzerFixtures.trend;
    const uploadPath = writeUploadableCsv(fixture);
    await openCsvTab(page);
    await uploadAndRun(page, uploadPath, fixture.service, fixture.metricName);

    await openRouterScoring(page);
    await expectRouterOutcome(page, analyzerId, 'Not recommended');
  } finally {
    await deleteCustomAnalyzerDraft(env.webUiBackendUrl, draftId, analyzerId);
  }
});
