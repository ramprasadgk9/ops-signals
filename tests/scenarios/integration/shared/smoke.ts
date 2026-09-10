import type { Page } from '@playwright/test';
import { expect } from '@playwright/test';

/**
 * Tier 1 smoke helper shared by every web-ui page spec: navigate, fail on any uncaught page
 * error (a React render crash surfaces here even if nothing else asserts it), and confirm the
 * persistent AppShell rendered — proving the route mounted inside the real app tree rather than,
 * say, an error boundary swallowing everything silently.
 */
export async function expectWebUiPageLoadsCleanly(page: Page, path: string): Promise<void> {
  const pageErrors: Error[] = [];
  page.on('pageerror', (error) => pageErrors.push(error));

  await page.goto(path);
  await expect(page.getByText('Ops Signals', { exact: true }).first()).toBeVisible({ timeout: 20_000 });

  expect(pageErrors, `Uncaught page error(s) on ${path}: ${pageErrors.map((e) => e.message).join('; ')}`).toHaveLength(0);
}
