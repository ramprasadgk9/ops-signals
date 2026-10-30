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

  // Each button takes you to the thing that ticks its step off: the handoff dialog, the finding.
  await guide.getByRole('button', { name: 'Open Shift handoff' }).click();
  await expect(page.getByRole('dialog')).toContainText('Shift handoff');
  await expect(page.getByTestId('demo-guide-pill')).toContainText('2 of 10');
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('demo-step-overview')).toHaveAttribute('data-done', 'true');

  await guide.getByRole('button', { name: 'Open the finding' }).click();
  await expect(page).toHaveURL(/\/findings\?service=checkout-api&finding=\d+/);
  // While the finding's details are open the guide shrinks to its button, out of the way.
  await expect(page.getByTestId('demo-guide-pill')).toContainText('3 of 10');
  await page.keyboard.press('Escape');

  await guide.getByRole('button', { name: 'Create the case' }).click();
  await expect(page).toHaveURL(/\/cases\/\d+\?tab=root-cause/);
  await page.getByRole('button', { name: 'Draft from case' }).click();
  await expect(page.getByTestId('demo-step-case')).toHaveAttribute('data-done', 'true');

  await guide.getByRole('button', { name: 'Hide' }).click();
  await expect(page.getByTestId('demo-guide-pill')).toContainText('4 of 10');
});

test('the rest of the steps go where they happen and tick themselves off', async ({ page }) => {
  // Steps 1-4 done (the test above walks them); start from 5.
  await page.goto('/');
  await page.evaluate(async () => {
    const demo = await (await fetch('/api/demo')).json();
    window.localStorage.setItem('ops-signals.demo.progress', JSON.stringify({ period: demo.resets_at ?? 'demo', done: ['alert', 'overview', 'pods', 'case'], hidden: false }));
  });
  await page.reload();
  const guide = page.getByTestId('demo-guide');
  const step = (id: string) => page.getByTestId(`demo-step-${id}`);

  await guide.getByRole('button', { name: 'Open the finding' }).click();
  await expect(page).toHaveURL(/service=payments-db&finding=\d+/);
  await expect(page.getByText(/This came back \d+ days after it was fixed/)).toBeVisible();
  await expect(page.getByTestId('demo-guide-pill')).toContainText('5 of 10');
  await page.goto('/');

  for (const [label, id, url] of [
    ['Open Recurring problems', 'recurring', /\/recurring-problems$/],
    ['Open Behavior Intelligence', 'patterns', /\/behavior-intelligence$/],
  ] as const) {
    await guide.getByRole('button', { name: label }).click();
    await expect(page).toHaveURL(url);
    await expect(step(id)).toHaveAttribute('data-done', 'true');
  }

  await guide.getByRole('button', { name: 'Open the finding' }).click();
  await expect(page).toHaveURL(/service=search-svc&finding=\d+/);
  await expect(page.getByTestId('demo-guide-pill')).toContainText('8 of 10');
  await page.goto('/');

  await guide.getByRole('button', { name: 'Open New Analysis' }).click();
  await page.getByTestId('demo-samples').getByRole('button', { name: 'Memory creeping up' }).click();
  await expect(step('analysis')).toHaveAttribute('data-done', 'true', { timeout: 60_000 });

  await guide.getByRole('button', { name: 'Open Ask Ops Signals' }).click();
  await page.getByPlaceholder(/Ask about cases/).fill('Have we seen payments-db connection pool problems before?');
  await page.getByPlaceholder(/Ask about cases/).press('Enter');
  await expect(guide).toContainText('All done');
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
