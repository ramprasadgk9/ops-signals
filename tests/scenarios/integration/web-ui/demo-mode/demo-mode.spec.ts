import { test, expect } from '@playwright/test';

/**
 * Demo mode (docs/demo.md, "Host it as a public demo"), against the demo stack started with
 * OPS_SIGNALS_DEMO_MODE=true and OPS_SIGNALS_WEB_UI_URL pointing at its web UI (port 8080 by default).
 * Skipped when the backend isn't in demo mode, so it can sit next to the dev-stack specs.
 */
test.beforeEach(async ({ page }) => {
  const demo = await (await page.request.get('/api/demo')).json();
  test.skip(!demo.enabled, 'the backend is not in demo mode');
});

test('a visitor sees the banner and the guide, and a step ticks itself off', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('demo-banner')).toContainText('Nothing here is real');
  const guide = page.getByTestId('demo-guide');
  await expect(guide).toContainText('Things to try');

  await guide.getByRole('button', { name: 'Open Alerts' }).click();
  await expect(page).toHaveURL(/\/alerts$/);
  await expect(page.getByTestId('demo-step-alert')).toHaveAttribute('data-done', 'true');

  await guide.getByRole('button', { name: 'Hide' }).click();
  await expect(page.getByTestId('demo-guide-pill')).toContainText('1 of 10');
});

test('settings are view-only, and the backend refuses them too', async ({ page }) => {
  await page.goto('/integrations');
  await expect(page.getByTestId('demo-turned-off')).toContainText('Turned off in the demo.');

  const refused = await page.request.post('/api/events', { data: [] });
  expect(refused.status()).toBe(403);
  expect((await refused.json()).detail).toContain('Turned off in the demo');
});

test('New Analysis offers sample files and ticks off its step', async ({ page }) => {
  await page.goto('/validate-data');
  const samples = page.getByTestId('demo-samples');
  await expect(samples).toContainText('Try a sample file');
  await samples.getByRole('button', { name: 'A sudden jump that stays' }).click();
  await expect(page.getByText(/Saved: \d+ samples/)).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId('demo-step-analysis')).toHaveAttribute('data-done', 'true');
});

test('a case draft is labeled as a recorded example when AI answers are recorded', async ({ page }) => {
  const demo = await (await page.request.get('/api/demo')).json();
  test.skip(demo.ai !== 'recorded', 'AI answers are not recorded on this site');
  const findings = await (await page.request.get('/api/findings?service=checkout-api&limit=20')).json();
  const finding = findings.find((item: { health_status: string }) => item.health_status !== 'normal');
  const created = await (await page.request.post(`/api/cases/findings/${finding.id}/create`, { data: {} })).json();

  await page.goto(`/cases/${created.case_id}`);
  await page.getByRole('tab', { name: /Root Cause/ }).click();
  await page.getByRole('button', { name: 'Draft from case' }).click();
  await expect(page.getByTestId('ai-recorded')).toContainText('Recorded example');
  await expect(page.getByTestId('demo-step-case')).toHaveAttribute('data-done', 'true');
});
