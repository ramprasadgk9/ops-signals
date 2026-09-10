import { test, expect } from '@playwright/test';
import { seedBehaviorFinding, cleanupBehaviorFinding } from '../../shared/db';

/**
 * Covers "dedup repeated detections instead of piling up duplicate rows" — the occurrence_count
 * / last_seen_at columns added to ops_behavior_findings and BehaviorIntelligenceService.save_or_bump
 * (backend/app/behavior_intelligence/repository.py). Seeds a finding directly with a known
 * occurrence_count/last_seen_at rather than waiting for save_or_bump to actually re-fire multiple
 * times, since GET /api/behavior-evaluations orders by created_at desc and this suite runs with
 * workers: 1 — the freshly seeded row lands first, same assumption toBehaviorRows/selected[0]
 * relies on.
 *
 * Also covers "show which pack file a rule came from" — the Rules tab's Source column and the
 * Patterns Library tab's source_file pill, both reading definition.source_file from the real
 * multi-file config/behavior_definitions.d loader (confirmed live earlier: core.yml, plus this
 * suite's own latency_and_errors.yml / memory_pressure.yml pack files all show up distinctly).
 */
test.describe('Behavior Intelligence — occurrence count and source file', () => {
  test('Detected Behaviors table shows occurrence count and last-seen for a seeded finding', async ({ page }) => {
    const service = `occurrence-smoke-${Date.now()}`;
    const title = `Occurrence smoke finding ${Date.now()}`;
    const findingId = await seedBehaviorFinding({
      service,
      title,
      occurrenceCount: 4,
      createdAt: new Date(Date.now() - 60 * 60_000),
      lastSeenAt: new Date(),
    });

    try {
      await page.goto('/behavior-intelligence');
      const row = page.locator('tr', { hasText: title });
      await expect(row).toBeVisible({ timeout: 15_000 });
      await expect(row.getByText(/^4× since/)).toBeVisible();
      await expect(row.getByText('just now')).toBeVisible();
    } finally {
      await cleanupBehaviorFinding(findingId);
    }
  });

  test('Rules tab and Patterns Library tab show which pack file each rule came from', async ({ page }) => {
    await page.goto('/behavior-intelligence');
    await page.getByRole('tab', { name: 'Rules' }).click();

    const cpuThrottlingRow = page.locator('tr', { hasText: 'Possible CPU throttling' });
    await expect(cpuThrottlingRow).toBeVisible({ timeout: 15_000 });
    await expect(cpuThrottlingRow.getByText('core.yml')).toBeVisible();

    const cascadeRow = page.locator('tr', { hasText: 'Possible cascading failure' });
    await expect(cascadeRow).toBeVisible();
    await expect(cascadeRow.getByText('latency_and_errors.yml')).toBeVisible();

    await page.getByRole('tab', { name: 'Patterns Library' }).click();
    await expect(page.getByText('Possible cascading failure', { exact: true })).toBeVisible({ timeout: 15_000 });
    // Patterns Library renders the source file through the shared Pill component, which
    // title-cases its label (see standalone/components.tsx) — "latency_and_errors.yml" renders
    // as "Latency And Errors.yml", not the raw filename.
    await expect(page.getByText('Latency And Errors.yml').first()).toBeVisible();
    await expect(page.getByText('Core.yml').first()).toBeVisible();
  });
});
