import { test, expect } from '@playwright/test';
import { env } from '../../shared/env';

/**
 * Plugin-only: the plugin can point at either the standalone backend (:8001) or the
 * Grafana-stack backend (:8002) — see backendOptions in frontend/src/grafana/PluginApp.tsx.
 * Only the web-ui suite doesn't have this axis, since the web-ui always talks to its own backend.
 */
test('switching the plugin backend target resets the service/metric selection', async ({ page }) => {
  await page.goto(env.pluginAppPath);

  const backendSelect = page.getByLabel('Ops Signals backend');
  await expect(backendSelect).toBeVisible({ timeout: 20_000 });

  const serviceInput = page.getByLabel('Service', { exact: true });
  await serviceInput.fill('some-service-to-be-cleared');
  await expect(serviceInput).toHaveValue('some-service-to-be-cleared');

  await backendSelect.selectOption({ label: 'Standalone app backend (:8001)' });
  await expect(serviceInput).toHaveValue('');

  await backendSelect.selectOption({ label: 'Grafana stack backend (:8002)' });
  await expect(serviceInput).toHaveValue('');
});
