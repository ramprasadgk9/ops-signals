import { test, expect, type Page } from '@playwright/test';
import { env } from '../../shared/env';
import { cleanupRun, createCaseFromFinding, makeRunId, seedFinding } from '../../shared/db';

/**
 * "Draft from case" on the Root Cause and Resolution tabs (backend/app/services/case_ai_drafts.py).
 * The AI status and drafts are stubbed, so the specs don't depend on whether the stack has an AI
 * provider; the backend's own answer is checked separately.
 */

async function seedCase(name: string): Promise<{ runId: string; findingId: number; caseId: number }> {
  const runId = makeRunId(name);
  const findingId = await seedFinding({ runId, service: 'checkout-api', metricName: 'db_connections_active', title: `Case AI drafts ${runId}` });
  const { case_id: caseId } = await createCaseFromFinding(env.webUiBackendUrl, findingId);
  return { runId, findingId, caseId };
}

async function stubAiOn(page: Page): Promise<void> {
  await page.route('**/api/ai/status', (route) =>
    route.fulfill({ json: { enabled: true, provider: 'ollama', model: 'test-model', endpoint: null, api_key_set: null, active: true, issue: null } })
  );
}

test('the backend answers a draft request with a reason when it has no draft', async ({ page }) => {
  const { runId, findingId, caseId } = await seedCase('case-ai-drafts-api');
  try {
    const response = await page.request.post(`${env.webUiBackendUrl}/api/cases/${caseId}/rca/suggest`, { data: {} });
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(body.available || ['ai_off', 'not_enough', 'failed'].includes(body.reason_code)).toBe(true);
  } finally {
    await cleanupRun({ runId, findingId });
  }
});

test('Draft from case fills the root cause, lists its sources, and only Save saves it', async ({ page }) => {
  const { runId, findingId, caseId } = await seedCase('case-ai-drafts-rca');
  const draft = 'A retry loop in v2.3 may not release DB connections on timeout (OPS-412).';
  await stubAiOn(page);
  await page.route(`**/api/cases/${caseId}/rca/suggest`, (route) =>
    route.fulfill({
      json: { available: true, draft, based_on_similar_cases: [], sources: [{ kind: 'ticket_comment', label: 'Ticket comment, Sam', detail: 'retry loop' }], reason_code: null },
    })
  );
  try {
    await page.goto(`/cases/${caseId}`);
    await page.getByRole('tab', { name: 'Root Cause' }).click();
    const panel = page.getByRole('tabpanel');
    await panel.getByRole('button', { name: 'Draft from case' }).click();

    await expect(panel.getByLabel('Root cause summary')).toHaveValue(draft);
    await expect(panel.getByTestId('case-draft-chip')).toBeVisible();
    await expect(panel.getByTestId('case-draft-sources')).toContainText('Ticket comment, Sam');

    const saved = await (await page.request.get(`${env.webUiBackendUrl}/api/cases/${caseId}`)).json();
    expect(saved.root_cause_summary).toBeNull();

    await panel.getByRole('button', { name: 'Save Root Cause' }).click();
    await expect(panel.getByTestId('case-draft-chip')).toHaveCount(0);
    await expect
      .poll(async () => (await (await page.request.get(`${env.webUiBackendUrl}/api/cases/${caseId}`)).json()).root_cause_summary)
      .toBe(draft);
  } finally {
    await cleanupRun({ runId, findingId });
  }
});

test('Draft from case fills both resolution boxes', async ({ page }) => {
  const { runId, findingId, caseId } = await seedCase('case-ai-drafts-resolution');
  await stubAiOn(page);
  await page.route(`**/api/cases/${caseId}/resolution/suggest`, (route) =>
    route.fulfill({
      json: { available: true, draft: 'Rolled back to v2.2; latency normal.', corrective_action: 'Rolled back. Still open: fix the retry loop.', sources: [], reason_code: null },
    })
  );
  try {
    await page.goto(`/cases/${caseId}`);
    await page.getByRole('tab', { name: 'Resolution' }).click();
    const panel = page.getByRole('tabpanel');
    await panel.getByRole('button', { name: 'Draft from case' }).click();

    await expect(panel.getByLabel('Outcome summary')).toHaveValue('Rolled back to v2.2; latency normal.');
    await expect(panel.getByLabel('Corrective action')).toHaveValue('Rolled back. Still open: fix the retry loop.');
  } finally {
    await cleanupRun({ runId, findingId });
  }
});
