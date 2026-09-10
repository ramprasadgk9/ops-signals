import { test, expect } from '@playwright/test';
import { runLabScenario, expectFindingCreated } from './labScenario';

/**
 * AnalyzerLabConfigPanel (the Save/Copy/Download/Clear component) is shared identically across
 * all 6 labs — verifying it once on Trend Lab covers the others too, since it's the same
 * component with the same backend contract (/api/analyzer-labs/config-suggestions), not
 * per-lab code.
 */
test('saving a lab YAML suggestion persists and appears in Saved Suggestions', async ({ page }) => {
  await runLabScenario(page, '/experiments/trend-lab', 'Steady up');
  await expectFindingCreated(page);

  const suggestionName = `Integration suite trend suggestion ${Date.now()}`;
  await page.getByLabel('Suggestion name').fill(suggestionName);
  await page.getByRole('button', { name: 'Save YAML Suggestion' }).click();

  await expect(page.getByText('Saved config suggestion.')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(suggestionName, { exact: true })).toBeVisible();

  // Clean up via the same panel's own action rather than reaching around it with a raw DB delete.
  await page.getByRole('button', { name: 'Clear All' }).click();
  await expect(page.getByText('Cleared saved suggestions for this analyzer.')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(suggestionName, { exact: true })).not.toBeVisible();
});
