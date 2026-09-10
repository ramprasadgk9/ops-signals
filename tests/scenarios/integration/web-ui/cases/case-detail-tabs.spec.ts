import { test, expect } from '@playwright/test';
import { env } from '../../shared/env';
import { makeRunId, seedFinding, createCaseFromFinding, cleanupRun } from '../../shared/db';

/**
 * Overview and Evidence are pure read-only display tabs (no mutations) — cheap to cover with real
 * seeded data. Publish Knowledge and Similar Cases both depend on Qdrant, which has been
 * unhealthy throughout this suite's development — smoke-only here (tab loads, doesn't crash),
 * not asserting actual indexing/similarity-search behavior, consistent with that scoping decision
 * elsewhere in this suite.
 */
test('case detail Overview, Evidence, Publish Knowledge, and Similar Cases tabs render seeded case data', async ({ page }) => {
  const runId = makeRunId('case-detail-tabs');
  const title = `Integration suite case-detail-tabs finding ${runId}`;
  const findingId = await seedFinding({
    runId,
    service: 'checkout-api',
    metricName: 'memory_usage',
    title,
  });
  const { case_id: caseId } = await createCaseFromFinding(env.webUiBackendUrl, findingId);

  try {
    await page.goto(`/cases/${caseId}`);

    // --- Overview (tab 0, default) ---
    await expect(page.getByText('Why this case exists')).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText(title, { exact: true }).first()).toBeVisible();
    await expect(page.getByText('Suggested focus')).toBeVisible();

    // --- Evidence (tab 1) ---
    await page.getByRole('tab', { name: 'Evidence' }).click();
    await expect(page.getByText('Signals used').first()).toBeVisible();
    await expect(page.getByText('No problem-signals matched.')).toBeVisible();
    await expect(page.getByText('Comparison details')).toBeVisible();

    // --- Publish Knowledge (tab 5) — smoke only, Qdrant-dependent action not exercised ---
    await page.getByRole('tab', { name: 'Publish Knowledge' }).click();
    await expect(page.getByText('Publish Knowledge', { exact: true }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: /Publish Knowledge|Refresh Knowledge|Published/ })).toBeVisible();
    await expect(page.getByText('Publish Checklist')).toBeVisible();

    // --- Similar Cases (tab 6) — smoke only; renders loading/empty/error state without crashing ---
    await page.getByRole('tab', { name: 'Similar Cases' }).click();
    await expect(
      page.getByText(/No similar cases found|Failed to load similar cases/).first()
    ).toBeVisible({ timeout: 20_000 });
  } finally {
    await cleanupRun({ runId, findingId });
  }
});
