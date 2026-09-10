import { test } from '@playwright/test';
import { expectWebUiPageLoadsCleanly } from '../../shared/smoke';

test('Investigations page loads without a crash', async ({ page }) => {
  await expectWebUiPageLoadsCleanly(page, '/investigations');
});
