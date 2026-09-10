import { test, expect } from '@playwright/test';
import { env } from '../../shared/env';
import { makeRunId, seedFinding, createCaseFromFinding, cleanupRun } from '../../shared/db';

/**
 * Search matches caseId/title/summary/service; status matches case_status OR investigation_status;
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

    // Severity filter: first combobox is status, second is severity (neither has an accessible
    // label tied to its purpose — both are named by their currently-selected option text).
    await page.getByPlaceholder('Search cases...').fill(runId);
    const severitySelect = page.getByRole('combobox').nth(1);
    await severitySelect.click();
    await page.getByRole('option', { name: 'Critical' }).click();
    await expect(page.getByText(criticalTitle, { exact: true })).toBeVisible();
    await expect(page.getByText(normalTitle, { exact: true })).not.toBeVisible();
  } finally {
    await cleanupRun({ runId, findingId: [criticalFindingId, normalFindingId] });
  }
});
