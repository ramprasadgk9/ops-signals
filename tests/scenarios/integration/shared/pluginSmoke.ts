import type { Page } from '@playwright/test';
import { expect } from '@playwright/test';
import { env } from './env';

/**
 * Plugin counterpart to shared/smoke.ts. The plugin has no client-side routes to navigate between
 * (module.ts registers a single app root page); "pages" are internal mode/stage states instead,
 * so this just confirms the plugin app itself mounts cleanly inside real Grafana.
 */
export async function expectPluginLoadsCleanly(page: Page): Promise<void> {
  const pageErrors: Error[] = [];
  page.on('pageerror', (error) => pageErrors.push(error));

  await page.goto(env.pluginAppPath);
  await expect(page.getByRole('button', { name: 'Interactive Analysis' })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole('button', { name: 'Autonomous Analysis' })).toBeVisible();

  expect(pageErrors, `Uncaught page error(s) on the plugin app: ${pageErrors.map((e) => e.message).join('; ')}`).toHaveLength(0);
}
