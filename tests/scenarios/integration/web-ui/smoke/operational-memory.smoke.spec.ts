import { test, expect } from '@playwright/test';
import { expectWebUiPageLoadsCleanly } from '../../shared/smoke';

test('Operational Memory page loads without a crash', async ({ page }) => {
  await expectWebUiPageLoadsCleanly(page, '/operational-memory');
  await expect(page.getByText('Memory Inventory')).toBeVisible();
});
