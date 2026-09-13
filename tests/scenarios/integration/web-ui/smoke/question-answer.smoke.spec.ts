import { test } from '@playwright/test';
import { expectWebUiPageLoadsCleanly } from '../../shared/smoke';

test('Question Answer page loads without a crash for an unknown question id', async ({ page }) => {
  // No DB-seeded question fixture exists yet; this confirms the route renders (including its
  // own not-found/error state) instead of crashing the app shell.
  await expectWebUiPageLoadsCleanly(page, '/questions/integration-suite-unknown-question');
});
