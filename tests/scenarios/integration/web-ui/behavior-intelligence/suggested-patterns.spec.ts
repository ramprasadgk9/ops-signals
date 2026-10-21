import { test, expect } from '@playwright/test';
import { existsSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import yaml from 'js-yaml';
import { makeRunId, seedSignal, cleanupRun, cleanupBehaviorPatternSuggestionsForService } from '../../shared/db';
import { env } from '../../shared/env';

/** The suggestion card around a card title: its nearest wrapper that holds the card's buttons. */
function ownCard(title: import('@playwright/test').Locator): import('@playwright/test').Locator {
  return title.locator('xpath=ancestor::*[.//button[normalize-space()="Dismiss"]][1]');
}

const PACK_DIR = path.resolve(__dirname, '../../../../../config/behavior_definitions.d');
// The page's "Save as is" button (promote) has no file picker — it always writes into this shared
// default (see queries.ts promoteBehaviorSuggestion's `packFile ?? 'suggested_patterns.yml'`), so
// cleanup must remove only this test's own entry, not the whole file — other promotions (real or
// from other test runs) may share it.
const DEFAULT_SUGGESTIONS_PACK = path.join(PACK_DIR, 'suggested_patterns.yml');

function removeDefinitionFromPack(definitionId: string): void {
  if (!existsSync(DEFAULT_SUGGESTIONS_PACK)) return;
  const doc = yaml.load(readFileSync(DEFAULT_SUGGESTIONS_PACK, 'utf-8')) as { behavior_definitions?: Record<string, unknown> } | null;
  if (!doc?.behavior_definitions || !(definitionId in doc.behavior_definitions)) return;
  delete doc.behavior_definitions[definitionId];
  if (Object.keys(doc.behavior_definitions).length === 0) {
    unlinkSync(DEFAULT_SUGGESTIONS_PACK);
  } else {
    writeFileSync(DEFAULT_SUGGESTIONS_PACK, yaml.dump(doc, { sortKeys: false }), 'utf-8');
  }
}

/**
 * Covers "let the system suggest combinations instead of guessing" — the co-occurrence pattern
 * miner (backend/app/behavior_intelligence/pattern_miner.py). Seeds 3 occasions of two metrics
 * whose signal windows land close together (within CO_OCCURRENCE_GAP=30min) on the same service,
 * meeting MIN_OCCASIONS=3 and MIN_CORRELATION_STRENGTH=0.5 so a real candidate surfaces, then
 * drives Mine -> review -> Save as is (promote) through the actual page.
 */
test.describe('Behavior Intelligence — suggested patterns', () => {
  test('mining seeded co-occurring signals surfaces a suggestion, which can be promoted to a pack', async ({ page }) => {
    const service = `suggested-pattern-smoke-${Date.now()}`;
    const metricA = 'mined_metric_alpha';
    const metricB = 'mined_metric_beta';
    const runIds: string[] = [];
    const base = new Date();

    try {
      for (let i = 0; i < 3; i += 1) {
        const runId = makeRunId(`suggested-pattern-occasion-${i}`);
        runIds.push(runId);
        const occasionStart = new Date(base.getTime() - (3 - i) * 2 * 60 * 60_000);
        const occasionEnd = new Date(occasionStart.getTime() + 5 * 60_000);
        await seedSignal({ runId, service, metricName: metricA, signalType: 'anomaly', startTime: occasionStart, endTime: occasionEnd });
        await seedSignal({ runId, service, metricName: metricB, signalType: 'anomaly', startTime: occasionStart, endTime: occasionEnd });
      }

      await page.goto('/behavior-intelligence');
      await page.getByRole('tab', { name: /^Patterns/ }).click();
      await page.locator('button:has-text("Mine Suggestions")').click();

      const suggestionCard = page.locator(`text=${metricA} + ${metricB} on ${service}`);
      await expect(suggestionCard).toBeVisible({ timeout: 15_000 });
      // Scoped to this test's own card: a database with real history has other pending
      // suggestions, and a page-wide Promote could promote one of them.
      const card = ownCard(suggestionCard);
      await expect(card.getByText(/Co-occurred 3 of 3 times \(100% correlation strength\)/)).toBeVisible();

      const definitionId = `suggested_${metricA}_${metricB}`;

      await card.getByRole('button', { name: 'Save as is' }).click();
      await expect(suggestionCard).not.toBeVisible({ timeout: 15_000 });

      const response = await page.request.get(`${env.webUiBackendUrl}/api/behavior-definitions/suggestions?status=promoted`);
      const promoted = await response.json();
      expect(promoted.some((s: { service: string }) => s.service === service)).toBe(true);

      const definitionsResponse = await page.request.get(`${env.webUiBackendUrl}/api/behavior-definitions`);
      const definitions = await definitionsResponse.json();
      const suggestedDefinition = definitions.find((d: { id: string }) => d.id === definitionId);
      expect(suggestedDefinition).toBeTruthy();
      expect(suggestedDefinition.source_file).toBe('suggested_patterns.yml');
      expect(existsSync(DEFAULT_SUGGESTIONS_PACK)).toBe(true);
      expect(readFileSync(DEFAULT_SUGGESTIONS_PACK, 'utf-8')).toContain(metricA);
    } finally {
      removeDefinitionFromPack(`suggested_${metricA}_${metricB}`);
      for (const runId of runIds) await cleanupRun({ runId });
      await cleanupBehaviorPatternSuggestionsForService(service);
    }
  });

  test('dismissing a suggestion removes it from the pending list without writing a pack file', async ({ page }) => {
    const service = `suggested-pattern-dismiss-${Date.now()}`;
    const metricA = 'mined_dismiss_alpha';
    const metricB = 'mined_dismiss_beta';
    const runIds: string[] = [];
    const base = new Date();

    try {
      for (let i = 0; i < 3; i += 1) {
        const runId = makeRunId(`suggested-pattern-dismiss-${i}`);
        runIds.push(runId);
        const occasionStart = new Date(base.getTime() - (3 - i) * 2 * 60 * 60_000);
        const occasionEnd = new Date(occasionStart.getTime() + 5 * 60_000);
        await seedSignal({ runId, service, metricName: metricA, signalType: 'anomaly', startTime: occasionStart, endTime: occasionEnd });
        await seedSignal({ runId, service, metricName: metricB, signalType: 'anomaly', startTime: occasionStart, endTime: occasionEnd });
      }

      await page.goto('/behavior-intelligence');
      await page.getByRole('tab', { name: /^Patterns/ }).click();
      await page.locator('button:has-text("Mine Suggestions")').click();

      const suggestionCard = page.locator(`text=${metricA} + ${metricB} on ${service}`);
      await expect(suggestionCard).toBeVisible({ timeout: 15_000 });

      await ownCard(suggestionCard).getByRole('button', { name: 'Dismiss' }).click();
      await expect(suggestionCard).not.toBeVisible({ timeout: 15_000 });

      const response = await page.request.get(`${env.webUiBackendUrl}/api/behavior-definitions/suggestions?status=dismissed`);
      const dismissed = await response.json();
      expect(dismissed.some((s: { service: string }) => s.service === service)).toBe(true);
    } finally {
      for (const runId of runIds) await cleanupRun({ runId });
      await cleanupBehaviorPatternSuggestionsForService(service);
    }
  });
});
