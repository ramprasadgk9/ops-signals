import { test } from '@playwright/test';
import { expectWebUiPageLoadsCleanly } from '../../shared/smoke';

test('Behavior Lab page loads without a crash', async ({ page }) => {
  await expectWebUiPageLoadsCleanly(page, '/behavior-intelligence/lab');
});
