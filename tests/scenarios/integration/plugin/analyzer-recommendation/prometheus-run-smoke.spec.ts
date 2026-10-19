import { test, expect } from '@playwright/test';
import { env } from '../../shared/env';

/**
 * The plugin's Interactive Analysis always queries live Prometheus through a real Grafana
 * datasource (no CSV upload, no seeded-sample picker on this surface — see the suite's plugin
 * Tier 2 scope note). This is a plumbing check, not a deterministic outcome assertion: it proves
 * datasource discovery -> query -> normalize -> backend analysis actually completes end-to-end
 * against dev/mock_prometheus_target.py's always-available "ops_signals_test_cpu_usage" series,
 * without asserting a specific analyzer outcome (real scrape history depth varies by how long the
 * stack has been up, so exact sample counts aren't controlled the way the web-ui's fixtures are).
 */
test('running an interactive analysis against live Prometheus completes and renders a result', async ({ page }) => {
  await page.goto(env.pluginAppPath);

  await page.getByLabel('Data source', { exact: true }).selectOption({ label: 'Prometheus' });
  await page.getByLabel('Service', { exact: true }).fill('test-trend-smooth-linear-increase');
  await page.getByLabel('Metric', { exact: true }).fill('ops_signals_test_cpu_usage');
  await page.getByRole('button', { name: 'Last 1h', exact: true }).click();

  await page.getByRole('button', { name: 'Run Analysis' }).click();
  await expect(page.getByText('Metric timeline')).toBeVisible({ timeout: 30_000 });
});
