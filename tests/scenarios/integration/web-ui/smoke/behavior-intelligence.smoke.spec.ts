import { test } from '@playwright/test';
import { expectWebUiPageLoadsCleanly } from '../../shared/smoke';

test('Behavior Intelligence page loads without a crash', async ({ page }) => {
  await expectWebUiPageLoadsCleanly(page, '/behavior-intelligence');
});
