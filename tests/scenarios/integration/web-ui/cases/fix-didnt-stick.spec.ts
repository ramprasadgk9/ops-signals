import { test, expect, type Page } from '@playwright/test';
import { env } from '../../shared/env';
import { cleanupRun, createCaseFromFinding, makeRunId, seedFinding } from '../../shared/db';

/**
 * "The fix that didn't stick" (backend/app/memory/fix_came_back.py): a finding or case back soon
 * after a past case on its service was fixed. Whether something came back depends on what memory
 * holds, so the came-back answers and the AI reasons are stubbed; the backend's own answer is
 * checked separately.
 */

const PAST = { case_id: 204, title: 'Checkout slow after deploy', fixed_at: '2026-10-24T15:10:00', days: 3, fix: 'Rolled back to v2.2.', still_open: 'fix the retry loop.' };

async function seedCase(name: string): Promise<{ runId: string; findingId: number; caseId: number }> {
  const runId = makeRunId(name);
  const findingId = await seedFinding({ runId, service: 'checkout-api', metricName: 'http_request_duration_p95', title: `Fix didn't stick ${runId}` });
  const { case_id: caseId } = await createCaseFromFinding(env.webUiBackendUrl, findingId);
  return { runId, findingId, caseId };
}

async function stubAiOn(page: Page): Promise<void> {
  await page.route('**/api/ai/status', (route) =>
    route.fulfill({ json: { enabled: true, provider: 'ollama', model: 'test-model', endpoint: null, api_key_set: null, active: true, issue: null } })
  );
}

test('the backend answers whether a case came back after a fix', async ({ page }) => {
  const { runId, findingId, caseId } = await seedCase('fix-came-back-api');
  try {
    const response = await page.request.get(`${env.webUiBackendUrl}/api/cases/${caseId}/fix-came-back`);
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(body.case_id).toBe(caseId);
    expect(typeof body.available).toBe('boolean');
  } finally {
    await cleanupRun({ runId, findingId });
  }
});

test('a case back soon after a fix names the old fix, and AI lists possible reasons on request', async ({ page }) => {
  const { runId, findingId, caseId } = await seedCase('fix-came-back-case');
  await stubAiOn(page);
  await page.route(`**/api/cases/${caseId}/fix-came-back`, (route) => route.fulfill({ json: { case_id: caseId, available: true, came_back: PAST } }));
  await page.route(`**/api/cases/${caseId}/fix-came-back/why`, (route) =>
    route.fulfill({ json: { available: true, reasons: ['The fix was a rollback, so the retry loop may still be in the code.'], sources: [], reason_code: null } })
  );
  try {
    await page.goto(`/cases/${caseId}`);
    const banner = page.getByTestId('fix-came-back');
    await expect(banner).toContainText('This came back 3 days after case #204 was fixed.');
    await expect(banner).toContainText('Fix then: Rolled back to v2.2.');
    await expect(banner).toContainText('Still open on that case: fix the retry loop.');
    await expect(banner.getByRole('link', { name: 'Open case #204 →' })).toHaveAttribute('href', '/cases/204');
    await expect(page.getByTestId('case-recurrence')).toHaveCount(0);

    await banner.getByRole('button', { name: 'Why might it not have held?' }).click();
    await expect(banner.getByTestId('fix-came-back-why')).toContainText('the retry loop may still be in the code');
    await expect(banner.getByTestId('fix-came-back-why')).toContainText('AI · not saved');
  } finally {
    await cleanupRun({ runId, findingId });
  }
});

test("the old case says its fix didn't hold and stays resolved", async ({ page }) => {
  const { runId, findingId, caseId } = await seedCase('fix-did-not-hold');
  await page.route(`**/api/cases/${caseId}/fix-came-back`, (route) =>
    route.fulfill({ json: { case_id: caseId, available: true, fix_outcome: { status: 'came_back', label: 'Came back after 3 days', came_back_case_id: 231, came_back_after_days: 3 } } })
  );
  try {
    await page.goto(`/cases/${caseId}`);
    await expect(page.getByTestId('fix-did-not-hold')).toContainText("This fix didn't hold: the problem came back 3 days later in case #231.");
    await expect(page.getByTestId('fix-did-not-hold-chip')).toHaveText("Fix didn't hold");
  } finally {
    await cleanupRun({ runId, findingId });
  }
});

test('finding details warn at the top when the finding is back soon after a fix, with no AI button when AI is off', async ({ page }) => {
  const runId = makeRunId('fix-came-back-finding');
  const findingId = await seedFinding({ runId, service: 'checkout-api', metricName: 'http_request_duration_p95', title: `Fix didn't stick finding ${runId}` });
  await page.route('**/api/ai/status', (route) =>
    route.fulfill({ json: { enabled: false, provider: 'none', model: null, endpoint: null, api_key_set: null, active: false, issue: null } })
  );
  await page.route(`**/api/findings/${findingId}/seen-before`, (route) =>
    route.fulfill({ json: { finding_id: findingId, available: true, service: 'checkout-api', matches: [], novelty: null, came_back: PAST } })
  );
  try {
    await page.goto(`/findings?finding=${findingId}`);
    const banner = page.getByTestId('fix-came-back');
    await expect(banner).toContainText('This came back 3 days after it was fixed.', { timeout: 20_000 });
    await expect(banner.getByRole('link', { name: '#204 Checkout slow after deploy' })).toHaveAttribute('href', '/cases/204');
    await expect(banner.getByRole('button')).toHaveCount(0);
  } finally {
    await cleanupRun({ runId, findingId });
  }
});
