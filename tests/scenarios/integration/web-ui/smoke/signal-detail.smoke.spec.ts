import { test } from '@playwright/test';
import { expectWebUiPageLoadsCleanly } from '../../shared/smoke';

test('Signal Detail page loads without a crash for an unknown signal id', async ({ page }) => {
  await expectWebUiPageLoadsCleanly(page, '/signals/integration-suite-unknown-signal');
});
