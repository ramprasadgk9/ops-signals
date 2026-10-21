import { test, expect } from '@playwright/test';
import { makeRunId, seedNormalizedPoints, seedSignal, cleanupRun } from '../../shared/db';

/**
 * Covers "See it on my data": POST /api/behavior-definitions/history-preview judges a draft on each
 * recent analysis run of a service, through the builder. Two seeded runs: in the newer one both
 * metrics rose together (ruptures signals, so change.upward is true for both); in the older one
 * only the first metric had a signal. The preview must say it would have fired in 1 of 2 runs and
 * why the other one did not.
 */
test.describe('Behavior Lab — see it on my data', () => {
  test('judges each recent run of the service and says why one did not match', async ({ page }) => {
    const service = `history-preview-${Date.now()}`;
    const newRun = makeRunId('history-preview-both');
    const oldRun = makeRunId('history-preview-one');
    const now = Date.now();
    const at = (hoursAgo: number) => new Date(now - hoursAgo * 60 * 60_000);
    const points = (hoursAgo: number) => [0, 1, 2].map((step) => ({ timestamp: at(hoursAgo + 2 - step), value: 10 + step }));

    for (const metricName of ['history_alpha', 'history_beta']) {
      await seedNormalizedPoints({ runId: newRun, service, metricName, points: points(0) });
      await seedNormalizedPoints({ runId: oldRun, service, metricName, points: points(30) });
      await seedSignal({ runId: newRun, service, metricName, signalType: 'ruptures', evidence: { percent_change: 60 }, startTime: at(2), endTime: at(0) });
    }
    await seedSignal({ runId: oldRun, service, metricName: 'history_alpha', signalType: 'ruptures', evidence: { percent_change: 60 }, startTime: at(32), endTime: at(30) });

    try {
      await page.goto('/behavior-intelligence/lab');
      await page.getByLabel('Id', { exact: true }).fill('history_preview_smoke');
      await page.getByLabel('Title', { exact: true }).fill('History preview smoke');
      await page.getByLabel('Output title', { exact: true }).fill('Alpha and beta rose together');

      await page.locator('button:has-text("Add Input")').click();
      await page.getByLabel('Alias', { exact: true }).first().fill('a');
      await page.getByLabel('Metric name', { exact: true }).first().fill('history_alpha');
      await page.locator('button:has-text("Add Input")').click();
      await page.getByLabel('Alias', { exact: true }).nth(1).fill('b');
      await page.getByLabel('Metric name', { exact: true }).nth(1).fill('history_beta');

      await page.locator('button:has-text("Add all condition")').click();
      await page.getByPlaceholder('cpu.anomaly.present').first().fill('a.change.upward');
      await page.locator('button:has-text("Add all condition")').click();
      await page.getByPlaceholder('cpu.anomaly.present').nth(1).fill('b.change.upward');

      await page.getByRole('combobox', { name: 'Service' }).fill(service);
      await page.getByRole('button', { name: 'See it on my data' }).click();

      await expect(page.getByText(`Would have fired in 1 of 2 runs of ${service}`, { exact: false })).toBeVisible({ timeout: 15_000 });
      const runs = page.getByRole('table', { name: 'Runs checked' });
      await expect(runs.getByText('Matched', { exact: true })).toBeVisible();
      await expect(runs.getByText('No signal for b: no change, or its analyzers did not run')).toBeVisible();
    } finally {
      await cleanupRun({ runId: newRun });
      await cleanupRun({ runId: oldRun });
    }
  });
});
