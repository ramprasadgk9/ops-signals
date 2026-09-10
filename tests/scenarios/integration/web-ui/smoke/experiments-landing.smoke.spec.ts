import { test, expect } from '@playwright/test';
import { expectWebUiPageLoadsCleanly } from '../../shared/smoke';

test('Experiments landing page loads without a crash', async ({ page }) => {
  await expectWebUiPageLoadsCleanly(page, '/experiments');
  await expect(page.getByText('Analyzer Experiment Dashboard')).toBeVisible();
});
