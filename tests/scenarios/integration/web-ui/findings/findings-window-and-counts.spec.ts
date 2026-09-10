import { test, expect } from '@playwright/test';
import { env } from '../../shared/env';
import { makeRunId, seedFinding, cleanupRun } from '../../shared/db';

/**
 * FindingsPage's KPI tiles are plain <p> siblings (value then label), not wrapped in a link like
 * Overview's KpiCard — locate the value by walking back from the label text, same xpath-sibling
 * pattern used elsewhere in this suite for unlabelled MUI elements.
 */
function kpiValue(page: import('@playwright/test').Page, label: string) {
  return page.getByText(label, { exact: true }).locator('xpath=preceding-sibling::p[1]');
}

async function fetchActiveFindings(window: '24h' | '7d') {
  const response = await fetch(`${env.webUiBackendUrl}/api/overview/summary?window=${window}`);
  return (await response.json()).active_findings as number;
}

test('seeding a finding increases the Findings In Window count for 24h but not for a finding outside it', async ({ page }) => {
  const runId = makeRunId('findings-window');
  const uniqueService = `findings-window-${runId}`;
  const baseline24h = await fetchActiveFindings('24h');
  const baseline7d = await fetchActiveFindings('7d');

  // Inside 24h and 7d.
  const recentFindingId = await seedFinding({
    runId,
    service: uniqueService,
    metricName: 'cpu_usage',
    title: `Integration suite findings-window recent ${runId}`,
  });
  // Outside 24h (2 days old), still inside 7d.
  const olderFindingId = await seedFinding({
    runId,
    service: uniqueService,
    metricName: 'cpu_usage',
    title: `Integration suite findings-window older ${runId}`,
    createdAt: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000),
  });

  try {
    await expect
      .poll(async () => fetchActiveFindings('24h'), { timeout: 15_000 })
      .toBe(baseline24h + 1);
    const after7d = await fetchActiveFindings('7d');
    expect(after7d).toBe(baseline7d + 2);

    await page.goto('/findings');
    await expect(page.getByRole('heading', { name: 'Findings', exact: true })).toBeVisible({ timeout: 20_000 });
    await expect(kpiValue(page, 'Active Findings')).toHaveText(String(baseline24h + 1));

    await page.getByRole('button', { name: 'Last 7 days' }).click();
    await expect
      .poll(async () => kpiValue(page, 'Active Findings').textContent(), { timeout: 15_000 })
      .toBe(String(baseline7d + 2));
  } finally {
    await cleanupRun({ runId, findingId: [recentFindingId, olderFindingId] });
  }
});
