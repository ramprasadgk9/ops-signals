import { test, expect, type Page } from '@playwright/test';
import { cleanupRun, makeRunId, seedFinding, seedSignal } from '../../shared/db';
import { env } from '../../shared/env';

/**
 * Finding details ask for AI wording after they show (GET /api/findings/{id}/ai-wording,
 * docs/finding-wording.md "AI wording"). The AI answer is stubbed, so the specs don't depend on
 * whether the stack has an AI provider; the backend's own answer is checked separately.
 */

async function seedGap(name: string): Promise<{ runId: string; findingId: number }> {
  const runId = makeRunId(name);
  const service = `ai-wording-${runId.slice(-8)}`;
  const lastSeen = new Date(Date.now() - 90 * 60_000);
  const resumed = new Date(Date.now() - 30 * 60_000);
  const signalId = await seedSignal({
    runId,
    service,
    metricName: 'orders_pending',
    signalType: 'data_gap',
    analyzerId: 'data_health',
    evidence: { gap_minutes: 60, interval_seconds: 60, last_seen: lastSeen.toISOString(), resumed_at: resumed.toISOString(), missing_points: 60, normal_missing_ratio: 0 },
    startTime: lastSeen,
    endTime: resumed,
  });
  const findingId = await seedFinding({ runId, service, metricName: 'orders_pending', category: 'data_quality', signalIds: [signalId] });
  return { runId, findingId };
}

async function stubAiWording(page: Page, findingId: number, body: object): Promise<void> {
  await page.route(`**/api/findings/${findingId}/ai-wording`, (route) => route.fulfill({ json: body }));
}

test('the backend answers for a finding with plain wording, AI on or off', async ({ page }) => {
  const { runId, findingId } = await seedGap('ai-wording-api');
  try {
    const response = await page.request.get(`${env.webUiBackendUrl}/api/findings/${findingId}/ai-wording`);
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(body.available || ['ai_off', 'failed'].includes(body.reason)).toBe(true);
  } finally {
    await cleanupRun({ runId, findingId });
  }
});

test('AI-written lines show with a chip and can be switched back to the template', async ({ page }) => {
  const { runId, findingId } = await seedGap('ai-wording-lines');
  const why = 'Pending orders stopped reporting, so nobody would see orders piling up.';
  await stubAiWording(page, findingId, { available: true, reason: null, why, check_extra: null, related_extra: null, model: 'test-model' });
  try {
    await page.goto(`/findings?finding=${findingId}`);
    const plain = page.getByTestId('finding-details-plain').getByTestId('finding-plain');
    await expect(plain).toContainText(why, { timeout: 20_000 });
    await expect(plain.getByTestId('finding-plain-ai')).toHaveCount(1);
    await expect(plain.getByTestId('finding-plain-ai-footer')).toContainText('Written by AI (test-model)');

    await plain.getByRole('button', { name: 'Show template wording' }).click();
    await expect(plain).not.toContainText(why);
    await expect(plain.getByTestId('finding-plain-ai')).toHaveCount(0);
  } finally {
    await cleanupRun({ runId, findingId });
  }
});

test('with AI off, the details offer how to turn it on until "Not now"', async ({ page }) => {
  const { runId, findingId } = await seedGap('ai-wording-hint');
  await stubAiWording(page, findingId, { available: false, reason: 'ai_off' });
  try {
    await page.goto(`/findings?finding=${findingId}`);
    const hint = page.getByTestId('enable-ai-hint');
    await expect(hint).toBeVisible({ timeout: 20_000 });

    await hint.getByRole('button', { name: 'How to turn it on' }).click();
    const dialog = page.getByRole('dialog', { name: 'Turn on AI wording' });
    await expect(dialog).toContainText('docker compose --profile ai up -d');
    await expect(dialog).toContainText('OPS_SIGNALS_AI_PROVIDER=ollama');
    await dialog.getByRole('button', { name: 'Close' }).click();

    await hint.getByRole('button', { name: 'Not now' }).click();
    await expect(hint).toHaveCount(0);
    await page.reload();
    await expect(page.getByTestId('finding-details-plain').getByTestId('finding-plain')).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId('enable-ai-hint')).toHaveCount(0);
  } finally {
    await cleanupRun({ runId, findingId });
  }
});
