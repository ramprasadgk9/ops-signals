import { expect, test } from '@playwright/test';
import { env } from '../../shared/env';

// Interactive Analysis through a Grafana data source (the default source) on a metric with one series
// per pod: the pods are combined into one line, as in the web UI's New Analysis, not interleaved.
//
// Needs a Grafana Prometheus data source with per-pod series - the demo stack's Prometheus has them
// (request_latency_p95 for search-svc, 4 pods). Add it in Grafana as e.g.
// "Demo Prometheus (pods test)" -> http://host.docker.internal:9096, or name another one in
// OPS_SIGNALS_PODS_DATASOURCE. Skipped when the data source isn't there.
const DATASOURCE = process.env.OPS_SIGNALS_PODS_DATASOURCE ?? 'Demo Prometheus (pods test)';
const SERVICE = process.env.OPS_SIGNALS_PODS_SERVICE ?? 'search-svc';
const METRIC = 'request_latency_p95';

test.beforeEach(async ({ page }) => {
  const login = await page.request.post('/login', { data: { user: env.grafanaUser, password: env.grafanaPassword } });
  expect(login.ok()).toBe(true);
});

async function fillForm(page: import('@playwright/test').Page, query: string) {
  await page.goto(env.pluginAppPath);
  const source = page.getByLabel('Data source', { exact: true });
  await expect(source).toBeVisible({ timeout: 20_000 });
  const names = await source.locator('option').allTextContents();
  test.skip(!names.includes(DATASOURCE), `No Grafana data source named "${DATASOURCE}" with per-pod series`);
  await source.selectOption({ label: DATASOURCE });
  await page.getByPlaceholder('Pick or type a service').fill(SERVICE);
  if (query !== METRIC) await page.getByRole('group', { name: 'Metric or PromQL' }).getByRole('button', { name: 'PromQL' }).click();
  await page.getByPlaceholder(query === METRIC ? 'Metric name' : 'PromQL expression').fill(query);
  await page.getByRole('button', { name: 'Last 1h' }).click();
  await page.getByRole('button', { name: 'Run Analysis' }).click();
}

test('a per-pod metric is analyzed as one line and the result says how', async ({ page }) => {
  await fillForm(page, METRIC);

  await expect(page.getByTestId('analyzed-as')).toContainText(/Analyzed as one line: the average of \d+ pods\./, { timeout: 120_000 });
});

test('a PromQL query that returns one series per pod stops with a plain message', async ({ page }) => {
  await fillForm(page, `${METRIC}{service="${SERVICE}"}`);

  await expect(page.getByText(/which differ by pod/)).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/Request failed: 400/)).toHaveCount(0);
});
