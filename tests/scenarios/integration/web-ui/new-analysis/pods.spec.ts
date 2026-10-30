import { test, expect } from '@playwright/test';

/**
 * New Analysis on a metric with one series per pod (docs/standalone-prometheus-analysis.md, "One
 * series per pod"). Needs the demo stack's search-svc, which has 4 pods and one that flaps
 * (docker-compose.demo.yml; OPS_SIGNALS_WEB_UI_URL pointing at its web UI). Skipped when the
 * connected Prometheus doesn't have those pods, so it can sit next to the dev-stack specs.
 */
const SELECTOR = 'request_latency_p95{service="search-svc"}';

test.beforeEach(async ({ page }) => {
  const res = await page.request.get(`/api/prometheus/label-values?label=pod&match=${encodeURIComponent(SELECTOR)}`);
  const pods: string[] = res.ok() ? (await res.json()).values : [];
  test.skip(pods.length < 3, 'the connected Prometheus has no per-pod search-svc series');
});

async function chooseSearchLatency(page: import('@playwright/test').Page) {
  await page.goto('/validate-data');
  // On the demo stack the "Things to try" guide sits over the form.
  const hideGuide = page.getByTestId('demo-guide').getByRole('button', { name: 'Hide' });
  if (await hideGuide.isVisible().catch(() => false)) await hideGuide.click();
  await page.getByRole('tab', { name: 'Prometheus' }).click();
  await page.getByPlaceholder('Select or type service').fill('search-svc');
  await page.getByPlaceholder('Select or type metric').fill('request_latency_p95');
  await page.getByRole('option', { name: 'request_latency_p95', exact: true }).click();
  await expect(page.getByLabel('PromQL')).toHaveValue(SELECTOR);
}

test('Run Analysis combines the pods without asking and says how', async ({ page }) => {
  await chooseSearchLatency(page);

  await page.getByRole('button', { name: 'Run Analysis' }).click();

  const note = page.getByTestId('combined-note');
  await expect(note).toContainText('Analyzed as one line: the average of 4 pods.', { timeout: 60_000 });
  await expect(note).toContainText('avg by (');
});

test('Preview shows the pods, names the odd one, and runs it alone', async ({ page }) => {
  await chooseSearchLatency(page);
  // The bad pod is slow 1 minute in every 5: a 5m step can sample around every burst.
  await page.getByLabel('Step / Interval').fill('1m');

  await page.getByRole('button', { name: 'Preview Data' }).click();

  const box = page.getByTestId('pod-combine-box');
  await expect(box).toContainText('4 pods report this metric.', { timeout: 30_000 });
  await expect(page.getByLabel('PromQL')).toHaveValue(/^avg by \(.*\) \(request_latency_p95\{service="search-svc"\}\)$/);
  await expect(box).toContainText('search-svc-2 is behaving differently from the other 3 pods');

  await box.getByRole('button', { name: 'Analyze only search-svc-2' }).click();
  await expect(page.getByLabel('PromQL')).toHaveValue('request_latency_p95{service="search-svc",pod="search-svc-2"}');

  await page.getByRole('button', { name: 'Run Analysis' }).click();
  await expect(page.getByText(/Analysis run \w+ created/)).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId('combined-note')).toHaveCount(0);
});

test('a hand-written query is kept as written, with Combine buttons to fix it', async ({ page }) => {
  await chooseSearchLatency(page);
  await page.getByText('Simple', { exact: true }).click();
  await page.getByRole('option', { name: 'Advanced PromQL' }).click();

  await page.getByRole('button', { name: 'Run Analysis' }).click();

  await expect(page.getByText(/which differ by pod/)).toBeVisible({ timeout: 30_000 });
  const box = page.getByTestId('pod-combine-box');
  await expect(box).toContainText('This query returns 4 lines, one per pod.');
  await box.getByRole('button', { name: 'Combine: highest pod' }).click();
  await expect(page.getByLabel('PromQL')).toHaveValue(/^max by \(.*\) \(request_latency_p95\{service="search-svc"\}\)$/);
});
