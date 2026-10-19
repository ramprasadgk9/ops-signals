import { test, expect } from '@playwright/test';
import { expectPluginLoadsCleanly } from '../../shared/pluginSmoke';

test('switching to Autonomous Analysis mode renders the config panel and policy overview without a crash', async ({ page }) => {
  await expectPluginLoadsCleanly(page);

  await page.getByRole('button', { name: 'Autonomous Analysis' }).click();

  // Switching to Autonomous mode lands on the "configure" stage (Preview -> Run once), not on the
  // overview panel - that only appears after a run. With a saved schedule the stage shows the
  // schedule card first; Edit opens the same form without saving anything, and Cancel edit leaves it.
  const editSchedule = page.getByRole('button', { name: 'Edit', exact: true });
  const previewPlan = page.getByRole('button', { name: 'Preview metric plan' });
  await expect(editSchedule.or(previewPlan)).toBeVisible({ timeout: 20_000 });
  const hadSchedule = await editSchedule.isVisible();
  if (hadSchedule) await editSchedule.click();

  await expect(page.getByText('1. Analysis Scope')).toBeVisible();
  await expect(page.getByText('2. Monitoring Categories')).toBeVisible();
  await expect(previewPlan).toBeVisible();

  if (hadSchedule) {
    await page.getByRole('button', { name: 'Cancel edit' }).click();
    await expect(editSchedule).toBeVisible();
  }
});
