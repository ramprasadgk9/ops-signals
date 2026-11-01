import { test, expect } from '@playwright/test';

/**
 * Settings in use (/analyzer-settings): every analyzer, whether a run uses it, and each setting's
 * value with the file it comes from. Read-only; it reads config files and changes nothing.
 */
test('Settings in use shows whether each analyzer runs and where its values come from', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Analyzer Workbench' }).click();
  await page.getByRole('link', { name: /Settings in use/ }).click();
  await expect(page).toHaveURL(/\/analyzer-settings$/);
  await expect(page.getByRole('heading', { name: 'Analyzer settings in use' })).toBeVisible();

  const layers = page.getByRole('list', { name: 'Where a setting comes from' });
  await expect(layers).toContainText('Built-in defaults');
  await expect(layers).toContainText('config/analyzers.yaml');
  await expect(layers).toContainText('config/analyzer_overrides.d/');
  await expect(layers).toContainText('Runs never use what you try there');
  await expect(page.getByText('How a run picks analyzers:')).toBeVisible();

  const glance = page.getByRole('region', { name: 'At a glance' });
  await expect(glance).toContainText('STUMPY and Data Health run on every metric.');
  await expect(glance).toContainText('Z-Score Anomaly');
  await expect(glance).toContainText('Labs are a sandbox: nothing tried there changes these settings.');

  const analyzers = page.getByRole('table', { name: 'Analyzers' });
  await expect(analyzers.getByRole('heading', { level: 3 }).first()).toHaveText('Run on every metric');
  await expect(analyzers.getByRole('heading', { name: 'The router picks them when they suit a metric' })).toBeVisible();
  await expect(analyzers.getByRole('heading', { name: "Don't run unless you choose them" })).toBeVisible();

  // STUMPY runs in discord mode, so its motif settings fold away as not used.
  await page.getByRole('button', { name: 'Show STUMPY settings' }).click();
  const stumpy = page.getByRole('table', { name: 'STUMPY settings' });
  await expect(stumpy).toContainText('implementation.max_discords');
  await expect(stumpy).not.toContainText('implementation.motif_count');
  await stumpy.getByRole('button', { name: /settings the analyzer doesn't use/ }).click();
  await expect(stumpy.getByRole('row').filter({ hasText: 'implementation.motif_count' })).toContainText('Not used');

  await page.getByRole('button', { name: 'Show Trend Analysis settings' }).click();
  const settings = page.getByRole('table', { name: 'Trend Analysis settings' });
  await expect(settings).toContainText('finding_rules.min_slope_percent');
  await expect(settings).toContainText('A team can change it');
  await expect(page.getByRole('link', { name: 'Try it in the Lab' })).toHaveAttribute('href', '/experiments/trend-lab');

  await page.getByRole('button', { name: 'How settings work' }).click();
  const dialog = page.getByRole('dialog', { name: 'How analyzer settings work' });
  await expect(dialog).toContainText('Which file do I edit?');
  await expect(dialog).toContainText("I changed a Lab. Why didn't my findings change?");
  await dialog.getByRole('button', { name: 'Close' }).last().click();
  await expect(dialog).toHaveCount(0);
});

test('Settings in use for a service no team file covers says it runs on the site-wide settings', async ({ page }) => {
  await page.goto('/analyzer-settings?service=no-team-file-service');
  await expect(page.getByText('No team\'s file changes no-team-file-service: it runs on the site-wide settings.')).toBeVisible();
});
