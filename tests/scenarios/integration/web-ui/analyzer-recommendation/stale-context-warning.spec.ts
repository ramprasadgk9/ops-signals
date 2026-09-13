import { test, expect } from '@playwright/test';

/**
 * E2E counterpart to frontend/src/test/scenarios/web-ui/analyzerRecommendation.scenario.test.tsx,
 * which covers the same warning at the component level with a mocked API.
 *
 * Correction from a live run: `stale` is computed server-side as
 * `bool(previous and previous.context_hash != context_hash)` (backend/app/metric_analyzer_recommendations/api.py:86)
 * — it compares THIS turn's context hash against the PREVIOUS turn's, keyed by conversation_id.
 * So it's false on a first call (no previous turn), and only becomes true on a second chat call,
 * within the same conversation, whose context actually changed. Editing a field alone does
 * nothing until the request is resent — this spec's first draft asserted the warning right after
 * editing without resubmitting, which the real backend never returns.
 */
test('resubmitting a changed metric context within the same conversation comes back flagged as stale', async ({ page }) => {
  await page.goto('/analyzer-recommendation');

  // "Memory Template" only fills operational_purpose/use_cases/operational_questions (see
  // metricTemplates.memory in AnalyzerRecommendationPage.tsx) — Metric Name/Description need to be
  // filled separately, confirmed against a live run.
  await page.getByLabel('Metric Name').fill('container_memory_usage_bytes');
  await page.getByLabel('Metric Description').fill('Current memory consumed by a Kubernetes container.');
  await page.getByRole('button', { name: 'Memory Template' }).click();
  await page.getByRole('button', { name: 'Get Preliminary Recommendation' }).click();
  await expect(page.getByText('Recommendation Results')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText('Metric context has changed. Reevaluate analyzers to refresh the recommendation.')).not.toBeVisible();

  await page.getByLabel('Metric Description').fill('Changed description to invalidate the prior context hash.');
  await page.getByRole('button', { name: 'Get Preliminary Recommendation' }).click();

  await expect(page.getByText('Metric context has changed. Reevaluate analyzers to refresh the recommendation.')).toBeVisible({
    timeout: 30_000,
  });
});
