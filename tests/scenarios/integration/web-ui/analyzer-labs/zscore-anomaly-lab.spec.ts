import { test, expect } from '@playwright/test';
import { runLabScenario, expectFindingCreated, expectNoFinding, passFailChip } from './labScenario';

test('Z-Score Anomaly Lab creates a finding for injected spikes and not for a clean baseline', async ({ page }) => {
  await runLabScenario(page, '/experiments/zscore-anomaly-lab', 'High spikes');
  await expectFindingCreated(page);
  await expect(passFailChip(page)).toHaveText('PASS');

  await runLabScenario(page, '/experiments/zscore-anomaly-lab', 'Clean baseline');
  await expectNoFinding(page);
  await expect(passFailChip(page)).toHaveText('PASS');
});
