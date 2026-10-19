import { expect, test } from '@playwright/test';
import { expectWebUiPageLoadsCleanly } from '../../shared/smoke';

test('Setup check page loads and lists the needed checks', async ({ page }) => {
  await expectWebUiPageLoadsCleanly(page, '/setup-check');
  await expect(page.getByRole('region', { name: 'Needed to start' })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole('region', { name: 'Needed to start' }).getByText('Backend', { exact: true })).toBeVisible();
});

test('the old System address opens Setup check', async ({ page }) => {
  await page.goto('/system');
  await expect(page).toHaveURL(/\/setup-check$/);
});
