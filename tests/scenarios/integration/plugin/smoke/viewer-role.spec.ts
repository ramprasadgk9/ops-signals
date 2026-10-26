import { expect, test } from '@playwright/test';
import { env } from '../../shared/env';

const PROXY = '/api/plugin-proxy/breezypoppy3596-opssignals-app/backend';
const VIEWER = { login: 'ops-signals-test-viewer', password: 'viewer-test-password' };
const admin = { Authorization: `Basic ${Buffer.from(`${env.grafanaUser}:${env.grafanaPassword}`).toString('base64')}` };

// A Grafana Viewer can look and ask, but Ops Signals locks what changes things (backend/app/roles.py).
test.beforeAll(async ({ request }) => {
  const created = await request.post(`${env.grafanaBaseUrl}/api/admin/users`, {
    headers: admin,
    data: { name: 'Test Viewer', login: VIEWER.login, email: `${VIEWER.login}@example.com`, password: VIEWER.password, OrgId: 1 },
  });
  // 412: the user is already there from an earlier run; new users join the org as Viewers.
  expect([200, 412]).toContain(created.status());
});

test('a Viewer sees what they cannot do, and the backend refuses it too', async ({ page }) => {
  const login = await page.request.post('/login', { data: { user: VIEWER.login, password: VIEWER.password } });
  expect(login.ok()).toBe(true);

  await page.goto(env.pluginAppPath);
  await expect(page.getByText(`${VIEWER.login} · Viewer`)).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole('button', { name: '🔒 Run Analysis' })).toBeDisabled();
  await expect(page.getByText('Editors can run analyses. Ask your Grafana admin for the Editor role.')).toBeVisible();

  // Reading still works through Grafana; a change is refused before it touches anything.
  expect((await page.request.get(`${PROXY}/api/autonomous/policies?limit=1`)).ok()).toBe(true);
  const refused = await page.request.post(`${PROXY}/api/findings/0/feedback`, { data: { verdict: 'real_problem' } });
  expect(refused.status()).toBe(403);
  expect((await refused.json()).detail).toContain('Ask your Grafana admin for the Editor role');

  // Set-up details are for Admins; the header chips read the summary every role may see.
  await expect(page.getByText('● Backend connected')).toBeVisible();
  const details = await page.request.get(`${PROXY}/api/setup/check`);
  expect(details.status()).toBe(403);
  expect((await details.json()).detail).toBe('Only Grafana admins can see this.');
  expect((await page.request.get(`${PROXY}/api/setup/summary`)).ok()).toBe(true);
});

test('a Viewer sees Autonomous Analysis without its set-up part', async ({ page }) => {
  const login = await page.request.post('/login', { data: { user: VIEWER.login, password: VIEWER.password } });
  expect(login.ok()).toBe(true);

  await page.goto(env.pluginAppPath);
  await expect(page.getByText(`${VIEWER.login} · Viewer`)).toBeVisible({ timeout: 20_000 });
  await page.getByRole('button', { name: /Autonomous Analysis/ }).click();

  // The schedule (or a note that there is none yet), never the Configure switch or the form.
  await expect(page.getByText(/^(Editors can change schedules\.|No schedule yet\.)$/).first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole('button', { name: 'Configure', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /^(🔒 )?Edit$/ })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /Save & schedule/ })).toHaveCount(0);
});

