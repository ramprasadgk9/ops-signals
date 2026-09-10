import { test, expect } from '@playwright/test';
import path from 'node:path';

const FIXTURE_PATH = path.resolve(__dirname, '../../../../../sample_data/ops_signals_test_series/01_ruptures_abrupt_regime_shift.csv');

/**
 * Unlike the 6 generate-and-run labs, this page takes a real CSV upload and calls a
 * routing-only endpoint (/api/experiment-analyzer-router/route, no pipeline execution, no
 * persistence). It lets you specify the value column name directly, so the existing
 * sample_data/ops_signals_test_series fixtures can be used as-is — no reshaping needed, unlike
 * the CSV-upload-routing-outcomes suite which uploads through the ingestion endpoint instead.
 * Reuses the same live-confirmed outcome for 01_ruptures_abrupt_regime_shift.csv as
 * shared/fixtures.ts's csvRouterOutcomes (ruptures: Recommended).
 */
test('uploading a CSV and running the router shows grouped routing decisions', async ({ page }) => {
  await page.goto('/analyzer-router');

  await page.getByLabel('Value column').fill('cpu_usage');
  await page.locator('input[type="file"]').setInputFiles(FIXTURE_PATH);
  await page.getByRole('button', { name: 'Run Router' }).click();

  await expect(page.getByText('Routing Decisions')).toBeVisible({ timeout: 20_000 });
  // The "Routing Decisions" outer Card also matches a broad `.MuiCard-root, has:"Ruptures"` filter
  // (confirmed live — it picked up every analyzer's recommendation chip, not just Ruptures's own).
  // display_name and recommendation render as sibling Chips in the same row — scope to the chip
  // itself and step to its immediate sibling instead.
  const recommendationChip = page.locator('.MuiChip-root').filter({ hasText: 'Ruptures' }).locator('xpath=following-sibling::div[1]');
  await expect(recommendationChip).toHaveText('RECOMMENDED');
});
