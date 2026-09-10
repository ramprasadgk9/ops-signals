import { test } from '@playwright/test';
import { expectWebUiPageLoadsCleanly } from '../../shared/smoke';

test('Overview page loads without a crash', async ({ page }) => {
  await expectWebUiPageLoadsCleanly(page, '/');
});
