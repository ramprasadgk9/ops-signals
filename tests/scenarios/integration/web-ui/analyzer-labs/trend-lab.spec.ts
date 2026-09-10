import { test } from '@playwright/test';
import { runLabScenario, expectFindingCreated, expectNoFinding, passFailChip } from './labScenario';
import { expect } from '@playwright/test';

test('Trend Lab creates a finding for a steady trend and not for a flat series', async ({ page }) => {
  await runLabScenario(page, '/experiments/trend-lab', 'Steady up');
  await expectFindingCreated(page);
  await expect(passFailChip(page)).toHaveText('PASS');

  await runLabScenario(page, '/experiments/trend-lab', 'Flat');
  await expectNoFinding(page);
  await expect(passFailChip(page)).toHaveText('PASS');
});
