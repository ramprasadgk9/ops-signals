import { expect, test } from '@playwright/test';
import { env } from '../../shared/env';

// The Configuration page is for Grafana admins, so this signs in (the other plugin tests run as the
// anonymous Viewer).
test('the Configuration page runs the Setup check against the plugin backend', async ({ page }) => {
  const pageErrors: Error[] = [];
  page.on('pageerror', (error) => pageErrors.push(error));

  // Through the login API: the login form stops on "Update your password" while the default is set.
  const login = await page.request.post('/login', { data: { user: env.grafanaUser, password: env.grafanaPassword } });
  expect(login.ok(), `Grafana login failed: ${login.status()}`).toBe(true);

  await page.goto('/plugins/breezypoppy3596-opssignals-app?page=configuration');
  const panel = page.getByRole('region', { name: 'Setup check' });
  const needed = panel.getByRole('region', { name: 'Needed to start' });
  await expect(needed).toBeVisible({ timeout: 30_000 });
  await expect(needed.getByText('Backend', { exact: true })).toBeVisible();
  await expect(needed.getByText('Database', { exact: true })).toBeVisible();

  expect(pageErrors, pageErrors.map((error) => error.message).join('; ')).toHaveLength(0);
});
