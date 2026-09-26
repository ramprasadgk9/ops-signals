import { test, expect } from '@playwright/test';
import { expectWebUiPageLoadsCleanly } from '../../shared/smoke';

// Read-only on purpose: "Send test alert" and "Load demo data" write to the shared stack (and the
// test alert can reach a real Slack channel), so they are covered by unit tests instead.
test('Integrations page loads and lists every data source', async ({ page }) => {
  await expectWebUiPageLoadsCleanly(page, '/integrations');
  await expect(page.getByRole('heading', { name: 'Integrations', exact: true })).toBeVisible();
  await expect(page.getByText('Send metrics via OTLP')).toBeVisible();
  await expect(page.getByText('Connect Alertmanager')).toBeVisible();
  await expect(page.getByText('Pull from Prometheus')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Load demo data' })).toBeVisible();
  await expect(page.getByText(/\/api\/otlp\/v1\/metrics$/).first()).toBeVisible();
  await expect(page.getByRole('status', { name: 'Data sources' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Alerts', exact: true })).toBeVisible();
});

test('Integrations is reachable from the sidebar', async ({ page }) => {
  await expectWebUiPageLoadsCleanly(page, '/');
  await page.getByRole('link', { name: 'Integrations' }).first().click();
  await expect(page).toHaveURL(/\/integrations$/);
  await expect(page.getByRole('heading', { name: 'Integrations', exact: true })).toBeVisible();
});
