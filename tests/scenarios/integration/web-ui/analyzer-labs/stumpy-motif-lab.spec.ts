import { test, expect } from '@playwright/test';
import { runLabScenario, expectFindingCreated, expectNoFinding, passFailChip } from './labScenario';

test('STUMPY Motif Lab creates a finding for a repeated motif and not for random noise', async ({ page }) => {
  await runLabScenario(page, '/experiments/stumpy-motif-lab', 'Repeated motif');
  await expectFindingCreated(page);
  await expect(passFailChip(page)).toHaveText('PASS');

  await runLabScenario(page, '/experiments/stumpy-motif-lab', 'No pattern');
  await expectNoFinding(page);
  await expect(passFailChip(page)).toHaveText('PASS');
});
