import { test, expect } from '@playwright/test';
import { expectWebUiPageLoadsCleanly } from '../../shared/smoke';

test('Cases list page loads without a crash and links into case detail', async ({ page }) => {
  await expectWebUiPageLoadsCleanly(page, '/cases');

  const firstCaseLink = page.locator('a[href^="/cases/"]').first();
  if (await firstCaseLink.count()) {
    await firstCaseLink.click();
    await expect(page).toHaveURL(/\/cases\/\d+/);
  }
});
