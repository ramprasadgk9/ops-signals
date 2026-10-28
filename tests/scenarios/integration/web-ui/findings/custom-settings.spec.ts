import { test, expect } from '@playwright/test';
import { makeRunId, seedAnalysisRun, seedFinding, seedSignal, setRunExecutedAnalyzers, cleanupRun } from '../../shared/db';

/**
 * A finding made with per-service analyzer settings (config/analyzer_overrides.d/) is tagged on its
 * card and its details show the setting next to the default, with the override's reason. Seeds the
 * run's execution record the way a run with an override writes it.
 */
test('a finding made with per-service settings says so, with the setting, default and reason', async ({ page }) => {
  const runId = makeRunId('custom-settings');
  const service = `payments-${runId}`;
  await seedAnalysisRun({ runId, service, metricName: 'memory_usage' });
  const signalId = await seedSignal({ runId, service, metricName: 'memory_usage', signalType: 'trend', analyzerId: 'trend' });
  const findingId = await seedFinding({ runId, service, metricName: 'memory_usage', title: `Memory climbing ${runId}`, signalIds: [signalId] });
  await setRunExecutedAnalyzers(runId, [
    {
      router_analyzer_id: 'trend_regression',
      pipeline_analyzer_ids: ['trend'],
      execution_status: 'completed',
      settings_overrides: [
        {
          series: [{ service, metric: 'memory_usage' }],
          applied: ['payments_memory'],
          params: { trend: { finding_rules: { min_slope_percent: 5 } } },
          disabled: [],
          overrides: [{ id: 'payments_memory', file: 'payments-team.yml', reason: 'Memory grows slowly here before an outage.' }],
          settings: [{ analyzer_id: 'trend', analyzer: 'Trend Analysis', path: 'finding_rules.min_slope_percent', label: 'Smallest steady climb or drop that counts', value: 5, default: 10 }],
        },
      ],
    },
  ]);

  try {
    await page.goto(`/findings?service=${service}`);
    const contextToggle = page.getByRole('button', { name: /Context only/ });
    await expect(page.getByRole('heading', { name: 'Findings', exact: true })).toBeVisible({ timeout: 20_000 });
    if ((await contextToggle.count()) && (await contextToggle.getAttribute('aria-expanded')) === 'false') await contextToggle.click();

    const chip = page.getByTestId('finding-custom-settings');
    await expect(chip).toHaveText('Custom settings · not tested');

    await page.goto(`/findings?finding=${findingId}`);
    const box = page.getByTestId('finding-custom-settings-box');
    await expect(box).toBeVisible({ timeout: 20_000 });
    await expect(box.getByRole('row', { name: /Trend Analysis: Smallest steady climb or drop that counts/ })).toContainText(/counts\s*5\s*10/); // value used, then the default
    await expect(box).toContainText('Memory grows slowly here before an outage.');
    await expect(page.getByTestId('finding-tested')).toContainText('Custom settings · not tested');
  } finally {
    await cleanupRun({ runId, findingId });
  }
});

test('Setup check shows the per-service settings row with How to set', async ({ page }) => {
  await page.goto('/setup-check');

  const howToSet = page.getByRole('button', { name: 'How to set: Per-service analyzer settings' });
  await expect(howToSet).toBeVisible({ timeout: 20_000 });
  await howToSet.click();
  await expect(page.getByText(/Copy config\/analyzer_overrides\.d\/payments-team\.yml\.example/)).toBeVisible();
  await expect(page.getByText(/Trend Analysis: Smallest steady climb or drop that counts/)).toBeVisible();
});
