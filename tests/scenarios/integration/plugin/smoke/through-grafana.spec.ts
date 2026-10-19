import { expect, test } from '@playwright/test';
import { env } from '../../shared/env';

const PROXY = '/api/plugin-proxy/breezypoppy3596-opssignals-app/backend';

// The local stack connects the plugin through Grafana (grafana/provisioning/plugins): Grafana calls the
// backend and says who the user is (backend/app/identity.py).
test('the plugin reaches the backend through Grafana, as the anonymous viewer', async ({ page }) => {
  await page.goto(env.pluginAppPath);

  await expect(page.getByText('Backend: through Grafana (set by your Grafana admin)')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole('button', { name: 'Change backend' })).toHaveCount(0);
  await expect(page.getByText('anonymous · Viewer')).toBeVisible();
});

test('a signed-in user is named on requests that go through Grafana', async ({ page }) => {
  const login = await page.request.post('/login', { data: { user: env.grafanaUser, password: env.grafanaPassword } });
  expect(login.ok()).toBe(true);

  const check = await page.request.get(`${PROXY}/api/setup/check`);
  expect(check.ok()).toBe(true);
  expect((await check.json()).you).toEqual({ name: env.grafanaUser, role: 'Admin', via: 'grafana' });

  await page.goto(env.pluginAppPath);
  await expect(page.getByText(`${env.grafanaUser} · Admin`)).toBeVisible({ timeout: 20_000 });
});
