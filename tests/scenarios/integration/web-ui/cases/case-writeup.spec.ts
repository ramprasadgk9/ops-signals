import { test, expect } from '@playwright/test';
import { env } from '../../shared/env';
import { cleanupRun, createCaseFromFinding, makeRunId, seedFinding } from '../../shared/db';

/**
 * Publish Knowledge: the case timeline (built from the case, no AI) and the write-up, saved with the
 * case and included in the text memory indexes. The AI status and draft are stubbed, so the spec
 * doesn't depend on whether the stack has an AI provider.
 */

test('the write-up is drafted, saved with the case, and shows in what memory will read', async ({ page }) => {
  const runId = makeRunId('case-writeup');
  const findingId = await seedFinding({ runId, service: 'checkout-api', metricName: 'db_connections_active', title: `Case write-up ${runId}` });
  const { case_id: caseId } = await createCaseFromFinding(env.webUiBackendUrl, findingId);
  const writeup = 'Summary: Rolled back to v2.2.\n\nStill open: fix the retry loop.';
  await page.route('**/api/ai/status', (route) =>
    route.fulfill({ json: { enabled: true, provider: 'ollama', model: 'test-model', endpoint: null, api_key_set: null, active: true, issue: null } })
  );
  await page.route(`**/api/cases/${caseId}/writeup/suggest`, (route) =>
    route.fulfill({ json: { available: true, draft: writeup, sources: [{ kind: 'root_cause', label: 'Saved root cause' }], reason_code: null } })
  );
  try {
    await page.goto(`/cases/${caseId}`);
    await page.getByRole('tab', { name: 'Publish Knowledge' }).click();
    const panel = page.getByRole('tabpanel');

    await expect(panel.getByTestId('case-timeline')).toContainText('Case opened', { timeout: 20_000 });

    await panel.getByRole('button', { name: 'Draft write-up' }).click();
    await expect(panel.getByLabel('Summary and lessons')).toHaveValue(writeup);
    await panel.getByRole('button', { name: 'Save only' }).click();

    await expect(panel.getByTestId('case-writeup-saved')).toContainText('Still open: fix the retry loop.');
    const saved = await (await page.request.get(`${env.webUiBackendUrl}/api/cases/${caseId}`)).json();
    expect(saved.writeup).toBe(writeup);

    await panel.getByRole('button', { name: 'What future searches will read' }).click();
    await expect(panel.getByTestId('case-memory-text')).toContainText('Write-up:');
  } finally {
    await cleanupRun({ runId, findingId });
  }
});
