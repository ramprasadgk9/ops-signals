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

test('Login shows the three steps and the next one', async ({ page }) => {
  await expectWebUiPageLoadsCleanly(page, '/setup-check');
  const recommended = page.getByRole('region', { name: 'Recommended' });
  const steps = recommended.getByRole('list', { name: 'Steps to control who can use Ops Signals' });
  await expect(steps).toBeVisible({ timeout: 20_000 });
  await expect(steps.getByRole('listitem')).toHaveCount(3);

  // Without a token (the local stack) the next step is locking the API, with the command to copy.
  const lock = recommended.getByRole('button', { name: 'Lock the API · 1 min: Login' });
  if (await lock.isVisible()) {
    await lock.click();
    await expect(recommended.getByText(/openssl rand -hex 32/)).toBeVisible();
  }
});
