import { expect, test, type Page } from '@playwright/test';

// What a signed-in Viewer sees in the web UI (backend/app/roles.py PAGES). The integration backend runs
// without sign-in, so the page list comes from the real GET /api/me and only the role is swapped in.
async function signInAsViewer(page: Page) {
  await page.route('**/api/me', async (route) => {
    const real = await (await route.fetch()).json();
    await route.fulfill({
      json: { ...real, signed_in: true, name: 'sam@example.com', role: 'Viewer', via: 'proxy', read_only_pages: ['/autonomous-monitoring'] },
    });
  });
}

test('a Viewer gets only their pages in the menu', async ({ page }) => {
  await signInAsViewer(page);
  await page.goto('/');
  const menu = page.getByRole('complementary');
  await expect(menu.getByRole('link', { name: 'Findings' })).toBeVisible({ timeout: 20_000 });
  await expect(menu.getByRole('link', { name: 'Autonomous Analysis', exact: true })).toBeVisible();
  for (const hidden of ['Integrations', 'New Analysis', 'Settings', 'Setup check']) {
    await expect(menu.getByRole('link', { name: hidden, exact: true })).toHaveCount(0);
  }
  await expect(menu.getByText('Analyzer Workbench')).toHaveCount(0);
});

test('a page opened by its address stays closed to a Viewer', async ({ page }) => {
  await signInAsViewer(page);
  await page.goto('/settings');
  await expect(page.getByRole('heading', { name: 'Settings is for Ops Signals admins' })).toBeVisible({ timeout: 20_000 });
  await page.getByRole('link', { name: 'Go to Overview' }).click();
  await expect(page).toHaveURL(/\/$/);
});

test('a Viewer sees Autonomous Analysis without its set-up form', async ({ page }) => {
  await signInAsViewer(page);
  await page.goto('/autonomous-monitoring');
  await expect(page.getByRole('heading', { name: 'Autonomous Analysis', exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('Configure Autonomous Analysis')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /Run once|Save/ })).toHaveCount(0);
});
