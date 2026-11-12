import { test, expect } from '@playwright/test';

/**
 * Recording rules in New Analysis (docs/standalone-prometheus-analysis.md, "What is a Recording
 * rule in the Metrics list?"). Needs these rules, in group lab-rules, on the lab Prometheus:
 *
 *   - record: service:error_rate:percent
 *     expr: 100 * avg by (service, env) (error_rate)
 *   - record: all_services_error_rate_percent
 *     expr: 100 * avg(error_rate)
 *
 * Skipped when the connected Prometheus doesn't have them, so it can sit next to the other specs.
 */
const RULE = 'service:error_rate:percent';
const ALL_SERVICES_RULE = 'all_services_error_rate_percent';

test.beforeEach(async ({ page }) => {
  const res = await page.request.get('/api/prometheus/recording-rules');
  const names: string[] = res.ok() ? (await res.json()).rules.map((rule: { name: string }) => rule.name) : [];
  test.skip(!names.includes(RULE) || !names.includes(ALL_SERVICES_RULE), 'the connected Prometheus has no lab-rules recording rules');
});

async function openPrometheus(page: import('@playwright/test').Page) {
  await page.goto('/validate-data');
  const hideGuide = page.getByTestId('demo-guide').getByRole('button', { name: 'Hide' });
  if (await hideGuide.isVisible().catch(() => false)) await hideGuide.click();
  await page.getByRole('tab', { name: 'Prometheus' }).click();
}

async function pickMetric(page: import('@playwright/test').Page, name: string) {
  await page.getByPlaceholder('Select or type metric').fill(name);
  await page.getByRole('option', { name: new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`) }).click();
}

test('the Metrics list tags recording rules', async ({ page }) => {
  await openPrometheus(page);

  await page.getByPlaceholder('Select or type metric').fill('service:');
  const option = page.getByRole('option', { name: new RegExp(`^${RULE}`) });
  await expect(option).toContainText('Recording rule');
  await expect(option).toContainText('lab-rules');
  await page.getByPlaceholder('Select or type metric').fill('cpu_usage');
  await expect(page.getByRole('option', { name: 'cpu_usage', exact: true })).not.toContainText('Recording rule');
});

test('picking a rule shows its saved query, and Run Analysis reads the saved points', async ({ page }) => {
  await openPrometheus(page);
  await page.getByPlaceholder('Select or type service').fill('spike-lab');
  await page.keyboard.press('Escape');
  await pickMetric(page, RULE);

  await expect(page.getByLabel('PromQL')).toHaveValue(`${RULE}{service="spike-lab"}`);
  const note = page.getByTestId('recording-rule-note');
  await expect(note).toContainText('Prometheus runs this query every 15s and saves the result under this name:');
  await expect(note).toContainText('100 * avg by (service, env) (error_rate)');
  await expect(note).toContainText('Built from error_rate');

  // The rule only has history since it was added: a short window and its own step give enough points.
  await page.getByLabel('Step / Interval').fill('15s');
  await page.getByRole('button', { name: 'Run Analysis' }).click();
  await expect(page.getByText(/Analysis run \w+ created/)).toBeVisible({ timeout: 60_000 });
});

test('a rule without the service label can be previewed but not analyzed', async ({ page }) => {
  await openPrometheus(page);
  await page.getByPlaceholder('Select or type service').fill('spike-lab');
  await page.keyboard.press('Escape');
  await pickMetric(page, ALL_SERVICES_RULE);

  const note = page.getByTestId('recording-rule-note');
  await expect(note).toContainText("This rule adds up all services, so its result doesn't belong to one service and can't be saved as a finding.");
  await expect(page.getByRole('button', { name: 'Run Analysis' })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Preview Data' })).toBeEnabled();
});

test('Run Analysis asks for a Service instead of failing', async ({ page }) => {
  await openPrometheus(page);
  await pickMetric(page, RULE);

  await expect(page.getByTestId('service-needed')).toContainText('Pick a Service to run the analysis');
  await expect(page.getByRole('button', { name: 'Run Analysis' })).toBeDisabled();
});
