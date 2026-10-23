import { test, expect } from '@playwright/test';

test('old Investigations link opens the In progress tab on Cases', async ({ page }) => {
  await page.goto('/investigations');
  await expect(page).toHaveURL(/\/cases\?tab=in-progress$/);
  await expect(page.getByRole('tab', { name: /^In progress \d+$/ })).toHaveAttribute('aria-selected', 'true');
});
