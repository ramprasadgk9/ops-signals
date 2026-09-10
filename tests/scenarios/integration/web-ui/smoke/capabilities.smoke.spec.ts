import { test, expect } from '@playwright/test';
import { expectWebUiPageLoadsCleanly } from '../../shared/smoke';

test('Capabilities page loads without a crash', async ({ page }) => {
  await expectWebUiPageLoadsCleanly(page, '/capabilities');
  await expect(page.getByText('Capabilities', { exact: true })).toBeVisible();
});
