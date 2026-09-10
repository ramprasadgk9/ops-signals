import { test, expect } from '@playwright/test';
import { expectWebUiPageLoadsCleanly } from '../../shared/smoke';

test('History page loads without a crash', async ({ page }) => {
  await expectWebUiPageLoadsCleanly(page, '/history');
  await expect(page.getByText('Analysis History')).toBeVisible();
});
