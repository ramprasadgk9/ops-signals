import { test, expect } from '@playwright/test';
import { runLabScenario, expectFindingCreated, expectNoFinding, passFailChip } from './labScenario';

test('Ruptures Change Point Lab creates a finding for a baseline shift and not when there is no shift', async ({ page }) => {
  await runLabScenario(page, '/experiments/ruptures-change-point-lab', 'Baseline shift up');
  await expectFindingCreated(page);
  await expect(passFailChip(page)).toHaveText('PASS');

  await runLabScenario(page, '/experiments/ruptures-change-point-lab', 'No shift');
  await expectNoFinding(page);
  await expect(passFailChip(page)).toHaveText('PASS');
});
