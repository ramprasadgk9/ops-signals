import { test, expect } from '@playwright/test';
import { makeRunId, seedFinding, getCaseByFindingId, cleanupRun } from '../../shared/db';

test('creating a case from a finding on the Findings page persists the correct snapshot in Postgres', async ({ page }) => {
  const runId = makeRunId('case-creation');
  const title = `Integration suite case-creation finding ${runId}`;
  const findingId = await seedFinding({
    runId,
    service: 'checkout-api',
    metricName: 'memory_usage',
    title,
  });

  try {
    await page.goto('/findings');
    // A generic `locator('div', { has: ... })` also matches every ancestor div of the title (not
    // just the card), and `.first()` picks the outermost one in DOM order — confirmed against a
    // live run, where that resolved two "Create Case" buttons. Scope to the MUI Card itself instead.
    const card = page.locator('.MuiCard-root', { has: page.getByText(title, { exact: true }) }).first();
    await card.getByRole('button', { name: 'Create Case' }).click();

    await page.waitForURL(/\/cases\/\d+/, { timeout: 15_000 });
    const caseId = Number(page.url().split('/cases/')[1]);
    await expect(page.getByText(title).first()).toBeVisible();

    const persistedCase = await getCaseByFindingId(findingId);
    expect(persistedCase).not.toBeNull();
    // ops_operational_cases.id is a Postgres bigint; node-postgres returns bigint columns as
    // strings (not numbers) to avoid silent precision loss above 2^53 — confirmed against a live
    // run. Coerce before comparing rather than relying on the driver's return type.
    expect(Number(persistedCase?.id)).toBe(caseId);
    expect((persistedCase?.finding_snapshot as { service?: string })?.service).toBe('checkout-api');
    expect((persistedCase?.finding_snapshot as { metric_name?: string })?.metric_name).toBe('memory_usage');
  } finally {
    await cleanupRun({ runId, findingId });
  }
});
