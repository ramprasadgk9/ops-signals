import { test, expect } from '@playwright/test';
import { env } from '../../shared/env';
import { DIRECT, setPluginConnection, THROUGH_GRAFANA } from '../../shared/pluginSettings';

/**
 * Plugin-only: the plugin can point at either the standalone backend (:8001) or the
 * Grafana-stack backend (:8002) — see localBackendOptions in frontend/src/grafana/backendUrlSetting.ts.
 * Only the web-ui suite doesn't have this axis, since the web-ui always talks to its own backend.
 * The picker exists only when the browser calls the backend directly, so this switches the plugin to
 * that mode and back (the local stack connects through Grafana).
 */
test.beforeAll(async ({ request }) => setPluginConnection(request, DIRECT));
test.afterAll(async ({ request }) => setPluginConnection(request, THROUGH_GRAFANA));

test('switching the plugin backend target resets the service/metric selection', async ({ page }) => {
  await page.goto(env.pluginAppPath);

  // The backend picker sits behind "change" next to the form's "Backend:" line.
  await page.getByRole('button', { name: 'Change backend' }).click({ timeout: 20_000 });
  const backendSelect = page.getByLabel('Ops Signals backend');
  await expect(backendSelect).toBeVisible();

  const serviceInput = page.getByLabel('Service', { exact: true });
  await serviceInput.fill('some-service-to-be-cleared');
  await expect(serviceInput).toHaveValue('some-service-to-be-cleared');

  await backendSelect.selectOption({ label: 'Standalone app backend (:8001)' });
  await expect(serviceInput).toHaveValue('');

  await backendSelect.selectOption({ label: 'Grafana stack backend (:8002)' });
  await expect(serviceInput).toHaveValue('');
});
