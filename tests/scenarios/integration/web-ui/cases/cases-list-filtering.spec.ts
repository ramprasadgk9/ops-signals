import { test, expect } from '@playwright/test';
import { env } from '../../shared/env';
import { makeRunId, seedFinding, createCaseFromFinding, cleanupRun } from '../../shared/db';

/**
 * Search matches caseId/title/summary/service/metric; status is a tab (Open, In progress, ...);
 * severity matches finding_snapshot.health_status exactly (lowercased) — see filterCaseRows() in
 * frontend/src/standalone/casesService.ts. Seeds two cases with deliberately different severities
 * so the severity filter has something real to narrow between.
 */
test('search and severity filters narrow the cases table to the expected rows', async ({ page }) => {
  const runId = makeRunId('cases-list-filter');
  const criticalTitle = `Integration suite critical case ${runId}`;
  const normalTitle = `Integration suite normal case ${runId}`;

  const criticalFindingId = await seedFinding({
    runId,
    service: 'checkout-api',
    metricName: 'error_rate',
    title: criticalTitle,
    healthStatus: 'critical',
  });
  const normalFindingId = await seedFinding({
    runId,
    service: 'payments-api',
    metricName: 'latency',
    title: normalTitle,
    healthStatus: 'normal',
  });
  const { case_id: criticalCaseId } = await createCaseFromFinding(env.webUiBackendUrl, criticalFindingId);
  const { case_id: normalCaseId } = await createCaseFromFinding(env.webUiBackendUrl, normalFindingId);

  try {
    await page.goto('/cases');

    // Search narrows to the one matching row by title substring.
    await page.getByPlaceholder('Search cases...').fill(runId);
    await expect(page.getByText(criticalTitle, { exact: true })).toBeVisible();
    await expect(page.getByText(normalTitle, { exact: true })).toBeVisible();
    await page.getByPlaceholder('Search cases...').fill(`critical case ${runId}`);
    await expect(page.getByText(criticalTitle, { exact: true })).toBeVisible();
    await expect(page.getByText(normalTitle, { exact: true })).not.toBeVisible();
    await page.getByPlaceholder('Search cases...').fill('');

    // Severity filter: the first combobox (named by its selected option text).
    // Scoped to <main> because the app header's global search is a combobox too.
    await page.getByPlaceholder('Search cases...').fill(runId);
    const severitySelect = page.getByRole('main').getByRole('combobox').first();
    await severitySelect.click();
    await page.getByRole('option', { name: 'Critical' }).click();
    await expect(page.getByText(criticalTitle, { exact: true })).toBeVisible();
    await expect(page.getByText(normalTitle, { exact: true })).not.toBeVisible();
  } finally {
    await cleanupRun({ runId, findingId: [criticalFindingId, normalFindingId] });
  }
});
