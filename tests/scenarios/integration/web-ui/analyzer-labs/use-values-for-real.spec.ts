import { test, expect } from '@playwright/test';
import { expectFindingCreated } from './labScenario';

/**
 * Every Lab says it's a sandbox, shows the value runs use under each field, and turns changed values
 * into a snippet for a team's override file or config/analyzers.yaml (AnalyzerLabConfigPanel, shared
 * by all 6 Labs, so Trend Lab covers the others). Nothing is saved: the snippet is copied by hand.
 */
test('a Lab says it is a sandbox and turns a changed value into a snippet for the right file', async ({ page }) => {
  await page.goto('/experiments/trend-lab');
  const banner = page.getByRole('note', { name: 'This Lab is a sandbox' });
  await expect(banner).toContainText('Nothing you try here changes real analysis runs');
  await expect(banner).toContainText('min_slope_percent 10');

  const slope = page.getByLabel('Min slope %');
  await expect(page.getByText('Runs use 10 (default)')).toBeVisible();
  const panel = page.getByRole('region', { name: 'Use these values for real' });
  await expect(panel).toContainText('Your values are the same as the values runs use now');

  await slope.fill('5');
  await expect(page.getByText('Changed · runs use 10 (default)')).toBeVisible();
  await expect(panel).toContainText('You changed 1 setting');

  await page.getByLabel('Pattern').click();
  await page.getByRole('option', { name: 'Steady up', exact: true }).click();
  await page.getByRole('button', { name: 'Run Analyzer' }).click();
  await expect(page.getByText(/^(FINDING_CREATED|NO_FINDING)$/)).toBeVisible({ timeout: 45_000 });
  await expectFindingCreated(page);
  await expect(panel).toContainText('With your values: a finding');
  await expect(panel).toContainText(/With the values runs use now: (a finding|no finding)/, { timeout: 45_000 });

  // A team's file is the default choice: only the changed key, under overrides → scope → analyzers.
  await panel.getByRole('combobox', { name: 'Service', exact: true }).fill('payments-api');
  await panel.getByLabel('Why these services need it').fill('Slow memory growth matters here');
  const snippet = panel.getByLabel('Snippet');
  await expect(snippet).toContainText('overrides:');
  await expect(snippet).toContainText('service: payments-api');
  await expect(snippet).toContainText('reason: "Slow memory growth matters here"');
  await expect(snippet).toContainText('min_slope_percent: 5');
  await expect(snippet).not.toContainText('library');
  await expect(panel.getByRole('button', { name: 'Download payments-api.yml' })).toBeVisible();

  // For every service: nested under analysis → analyzers, where config/analyzers.yaml reads it.
  await panel.getByRole('radio', { name: 'For every service' }).check();
  await expect(snippet).toContainText('analysis:');
  expect(await snippet.textContent()).toBe('analysis:\n  analyzers:\n    trend:\n      finding_rules:\n        min_slope_percent: 5\n');

  await page.getByRole('button', { name: 'Reset' }).click();
  await expect(panel).toContainText('Your values are the same as the values runs use now');
  await expect(page.getByRole('button', { name: 'Save YAML Suggestion' })).toHaveCount(0);
});

test('a Lab for an analyzer the router never picks warns that the setting alone changes nothing', async ({ page }) => {
  await page.goto('/experiments/zscore-anomaly-lab');
  await page.getByLabel('Min abs z-score').fill('4');
  const panel = page.getByRole('region', { name: 'Use these values for real' });
  await expect(panel).toContainText("doesn't run on its own in your setup");
  await expect(panel).toContainText('selection_mode: all');
});
