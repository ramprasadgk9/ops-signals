import { test, expect } from '@playwright/test';
import { existsSync, readFileSync, unlinkSync } from 'node:fs';
import path from 'node:path';
import { env } from '../../shared/env';

const PACK_DIR = path.resolve(__dirname, '../../../../../config/behavior_definitions.d');

/**
 * Covers "save an authored pattern as its own pack file" — the multi-file behavior_definitions.d
 * loader improvement. Saves through the real UI, confirms the YAML landed on disk with the right
 * shape, and confirms GET /api/behavior-definitions reports it back with source_file set to the
 * pack file — proving loader.py actually picked it up, not just that the write succeeded.
 */
test.describe('Behavior Lab — save to pack', () => {
  test('saving a valid definition writes a new pack file the loader picks up', async ({ page }) => {
    const packFile = `integration_test_save_to_pack_${Date.now()}.yml`;
    const packPath = path.join(PACK_DIR, packFile);
    const definitionId = `save_to_pack_smoke_${Date.now()}`;

    try {
      await page.goto('/behavior-intelligence/lab');
      await page.getByLabel('Id', { exact: true }).fill(definitionId);
      await page.getByLabel('Title', { exact: true }).fill('Save to pack smoke test');
      await page.getByLabel('Output title', { exact: true }).fill('Save to pack smoke output');

      await page.locator('button:has-text("Add Input")').click();
      await page.getByLabel('Alias', { exact: true }).first().fill('cpu');
      await page.getByLabel('Metric name', { exact: true }).first().fill('cpu_usage');
      await page.locator('button:has-text("Add Input")').click();
      await page.getByLabel('Alias', { exact: true }).nth(1).fill('memory');
      await page.getByLabel('Metric name', { exact: true }).nth(1).fill('memory_usage');

      // Added in plain words: "cpu is rising".
      await page.locator('button:has-text("Add all condition")').click();

      await page.getByLabel('Pack file', { exact: true }).fill(packFile);
      await page.locator('button:has-text("Save to Pack")').click();

      await expect(page.getByText(`Saved to config/behavior_definitions.d/${packFile}.`)).toBeVisible({ timeout: 15_000 });

      expect(existsSync(packPath)).toBe(true);
      const yamlText = readFileSync(packPath, 'utf-8');
      expect(yamlText).toContain(definitionId);
      expect(yamlText).toContain('cpu_usage');
      expect(yamlText).toContain('memory_usage');
      expect(yamlText).toContain('cpu.change.upward');

      const response = await page.request.get(`${env.webUiBackendUrl}/api/behavior-definitions`);
      const definitions = await response.json();
      const saved = definitions.find((d: { id: string }) => d.id === definitionId);
      expect(saved).toBeTruthy();
      expect(saved.source_file).toBe(packFile);
    } finally {
      if (existsSync(packPath)) unlinkSync(packPath);
    }
  });

  test('saving an invalid definition is refused and no file is written', async ({ page }) => {
    const packFile = `integration_test_save_to_pack_invalid_${Date.now()}.yml`;
    const packPath = path.join(PACK_DIR, packFile);

    try {
      await page.goto('/behavior-intelligence/lab');
      await page.getByLabel('Id', { exact: true }).fill('save_to_pack_invalid_smoke');
      await page.getByLabel('Title', { exact: true }).fill('Save to pack invalid smoke');
      await page.getByLabel('Output title', { exact: true }).fill('Should be refused');
      // No inputs, no conditions — deliberately invalid.
      await page.getByLabel('Pack file', { exact: true }).fill(packFile);
      await page.locator('button:has-text("Save to Pack")').click();

      await expect(page.getByText(/definition must declare at least one input/)).toBeVisible({ timeout: 15_000 });
      expect(existsSync(packPath)).toBe(false);
    } finally {
      if (existsSync(packPath)) unlinkSync(packPath);
    }
  });
});
