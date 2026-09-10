import { test } from '@playwright/test';
import { expectWebUiPageLoadsCleanly } from '../../shared/smoke';

test('Autonomous Monitoring page loads without a crash', async ({ page }) => {
  await expectWebUiPageLoadsCleanly(page, '/autonomous-monitoring');
});
