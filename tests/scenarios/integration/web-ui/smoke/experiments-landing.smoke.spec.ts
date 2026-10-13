import { test, expect } from '@playwright/test';
import { expectWebUiPageLoadsCleanly } from '../../shared/smoke';

// The Experiments page was removed; old /experiments links land on the Ruptures Change Point Lab.
test('old Experiments links open the Ruptures Change Point Lab without a crash', async ({ page }) => {
  await expectWebUiPageLoadsCleanly(page, '/experiments');
  await expect(page).toHaveURL(/\/experiments\/ruptures-change-point-lab$/);
  await expect(page.getByRole('heading', { name: 'Ruptures Change Point Lab' })).toBeVisible();
});
