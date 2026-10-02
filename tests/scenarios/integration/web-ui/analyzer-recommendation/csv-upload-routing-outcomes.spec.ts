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
 * Expected outcomes are captured from a live run (2026-09-08), not from
 * sample_data/ops_signals_test_series/README.md's "Expected routing behavior" table — that table
 * disagrees with the live router for fixture 04 (see below and analyzerFixtures.pyodOutlier's
 * comment in shared/fixtures.ts). This suite asserts real behavior so it catches real regressions
 * from today's baseline; the README-vs-router discrepancy itself is a separate open question for
 * the team, not something resolved here.
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

function bucketCard(page: import('@playwright/test').Page, bucketLabel: string) {
  // Each bucket renders as its own Card with a heading matching routerBucketLabel() exactly
  // (Recommended / Optional / Rejected / Not Recommended) — see ValidateDataPage.tsx. Scoping to
  // the Card (not a bare div) avoids matching every ancestor div of the heading text.
  return page.locator('.MuiCard-root', { has: page.getByText(bucketLabel, { exact: true }) });
}

for (const key of ['ruptures', 'trend', 'stumpy', 'pyodOutlier', 'mixed'] as const) {
  const fixture = analyzerFixtures[key];

  test(`CSV upload of ${fixture.file} routes analyzers as observed live`, async ({ page }) => {
    const uploadPath = writeUploadableCsv(fixture);
    await openCsvTab(page);
    await uploadAndRun(page, uploadPath, fixture.service, fixture.metricName);

    for (const [analyzerId, bucketLabel] of Object.entries(fixture.csvRouterOutcomes)) {
      await expect(bucketCard(page, bucketLabel).getByText(analyzerId, { exact: true })).toBeVisible();
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

    await expect(bucketCard(page, 'Not Recommended').getByText(analyzerId, { exact: true })).toBeVisible();
  } finally {
    await deleteCustomAnalyzerDraft(env.webUiBackendUrl, draftId, analyzerId);
  }
});
