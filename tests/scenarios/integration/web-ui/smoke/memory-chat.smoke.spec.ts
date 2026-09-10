import { test } from '@playwright/test';
import { expectWebUiPageLoadsCleanly } from '../../shared/smoke';

test('Memory Chat / Assistant page loads without a crash', async ({ page }) => {
  await expectWebUiPageLoadsCleanly(page, '/assistant');
});

test('Memory Chat page also loads without a crash at its alternate route', async ({ page }) => {
  await expectWebUiPageLoadsCleanly(page, '/memory-chat');
});
