import { test, expect } from '@playwright/test';
import { env } from '../../shared/env';
import { makeRunId, seedFinding, createCaseFromFinding, cleanupRun } from '../../shared/db';

/**
 * OverviewPage aggregates ALL findings/cases in the 24h window (there's no window switcher UI on
 * this page — it's hardcoded to '24h', confirmed reading OverviewPage.tsx), so asserting an exact
 * KPI number would be fragile in a shared dev database. Instead: capture a baseline via the same
 * API the page calls, seed one new finding+case with a service name that can't already be
 * impacting anything, and assert each KPI increased by exactly 1 — robust regardless of whatever
 * else is in the database.
 */
async function fetchSummary() {
  const response = await fetch(`${env.webUiBackendUrl}/api/overview/summary?window=24h`);
  return response.json() as Promise<{ active_findings: number; attention_findings: number; open_cases: number; impacted_services: number }>;
}

test('creating a finding and case increases the Overview KPI tiles by exactly one', async ({ page }) => {
  const runId = makeRunId('overview-kpi');
  const uniqueService = `overview-kpi-${runId}`;
  const baseline = await fetchSummary();

  const findingId = await seedFinding({
    runId,
    service: uniqueService,
    metricName: 'cpu_usage',
    title: `Integration suite overview-kpi finding ${runId}`,
  });
  await createCaseFromFinding(env.webUiBackendUrl, findingId);

  try {
    await expect
      .poll(async () => (await fetchSummary()).active_findings, { timeout: 15_000 })
      .toBe(baseline.active_findings + 1);
    const afterSeed = await fetchSummary();
    expect(afterSeed.open_cases).toBe(baseline.open_cases + 1);
    expect(afterSeed.impacted_services).toBe(baseline.impacted_services + 1);

    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible({ timeout: 20_000 });

    // The tile counts the problems needing attention; the rest are one click away in context.
    const attentionTile = page.locator('a', { has: page.getByText('Need Attention', { exact: true }) });
    await expect(attentionTile.locator('p').first()).toHaveText(String(afterSeed.attention_findings));

    const openCasesTile = page.locator('a', { has: page.getByText('Open Cases', { exact: true }) });
    await expect(openCasesTile.locator('p').first()).toHaveText(String(afterSeed.open_cases));
  } finally {
    await cleanupRun({ runId, findingId });
  }
});
