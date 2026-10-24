import { test, expect } from '@playwright/test';
import { expectWebUiPageLoadsCleanly } from '../../shared/smoke';

// Operational Memory was renamed Recurring problems; the old link still opens it.
test('Recurring problems page loads without a crash', async ({ page }) => {
  await expectWebUiPageLoadsCleanly(page, '/recurring-problems');
  await expect(page.getByRole('heading', { name: 'Recurring problems' })).toBeVisible();
});

test('old Operational Memory link opens Recurring problems', async ({ page }) => {
  await page.goto('/operational-memory');
  await expect(page).toHaveURL(/\/recurring-problems$/);
  await expect(page.getByRole('heading', { name: 'Recurring problems' })).toBeVisible();
});
