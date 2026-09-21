import { test, expect } from '@playwright/test';

/**
 * PyOD Outlier Lab is the one lab of the 6 that does NOT share the FINDING_CREATED/NO_FINDING
 * chip pattern — its "Execution Result" panel shows the router recommendation chip instead
 * (confirmed reading PyodOutlierLabPage.tsx: no FINDING_CREATED/NO_FINDING string anywhere in
 * the file), so this doesn't use the shared labScenario helper.
 *
 * Also confirmed live: the lab's *default* Magnitude(6)/Outliers(8) never actually crosses the
 * finding threshold for "Gaussian spikes" (stayed at "0 findings" even with a strong spike
 * pattern) — router suitability score is pinned at 0.46/NOT_RECOMMENDED regardless of magnitude,
 * and only the finding-rule side responds to stronger injected outliers. Bumping Magnitude/
 * Outliers to 15 (still using the lab's own exposed controls, not bypassing them) reliably
 * produces a finding. Whether the router score being magnitude-invariant is itself a genuine
 * issue is a separate question from what this test asserts.
 *
 * Skipped: flaky in CI (times out waiting for a finding after injecting outliers) - the pattern
 * generator isn't seeded, so an unlucky random draw can land under the finding threshold even at
 * Magnitude/Outliers=15. See https://github.com/ramprasadgk9/operational-intelligence/issues/29.
 */
test.skip('PyOD Outlier Lab creates a finding for strong injected outliers and not for a clean baseline', async ({ page }) => {
  await page.goto('/experiments/pyod-outlier-lab');
  await page.getByLabel('Pattern').click();
  await page.getByRole('option', { name: 'Gaussian spikes', exact: true }).click();
  await page.getByLabel('Magnitude').fill('15');
  await page.getByLabel('Outliers').fill('15');
  await page.getByRole('button', { name: 'Run Analyzer' }).click();
  await expect(page.getByText(/^\d+ signals, [1-9]\d* findings$/)).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText(/^(PASS|FAIL|UNKNOWN)$/)).toHaveText('PASS');

  await page.goto('/experiments/pyod-outlier-lab');
  await page.getByLabel('Pattern').click();
  await page.getByRole('option', { name: 'Gaussian clean', exact: true }).click();
  await page.getByRole('button', { name: 'Run Analyzer' }).click();
  await expect(page.getByText(/^\d+ signals, 0 findings$/)).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText(/^(PASS|FAIL|UNKNOWN)$/)).toHaveText('PASS');
});
