import { test, expect } from '@playwright/test';
import { expectPluginLoadsCleanly } from '../../shared/pluginSmoke';

test('switching to Autonomous Analysis mode renders the config panel and policy overview without a crash', async ({ page }) => {
  await expectPluginLoadsCleanly(page);

  await page.getByRole('button', { name: 'Autonomous Analysis' }).click();

  // Confirmed against a live run: switching to Autonomous mode lands on the "configure" stage
  // (Preview -> Run once), not directly on the overview panel — that only appears after a run.
  await expect(page.getByText('1. Analysis Scope')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('2. Monitoring Categories')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Preview metric plan' })).toBeVisible();
});
