import { test, expect } from '@playwright/test';

/**
 * Covers the "self-service pattern authoring" improvement: the Advanced: all facts panel (real facts
 * from GET /api/behavior-definitions/facts, not a hardcoded list) and the Validate button's
 * structural checks (BehaviorDefinitionValidator — backend/app/behavior_intelligence/validator.py),
 * confirmed live against the actual error/warning strings the backend returns.
 */
test.describe('Behavior Lab — fact reference and validation', () => {
  test('Advanced: all facts lists real facts from the backend catalog', async ({ page }) => {
    await page.goto('/behavior-intelligence/lab');
    await page.getByRole('button', { name: /Advanced: all facts/ }).click();
    // anomaly.present is one of FACT_DESCRIPTORS in fact_catalog.py — confirms this renders the
    // real catalog rather than an empty or stubbed panel.
    await expect(page.getByText('anomaly.present', { exact: true })).toBeVisible();
    await expect(page.getByText('Whether any anomaly signal was found for this metric in the window.')).toBeVisible();
  });

  test('Validate reports a definition with no inputs as invalid', async ({ page }) => {
    await page.goto('/behavior-intelligence/lab');
    await page.getByLabel('Id', { exact: true }).fill('validation_smoke_no_inputs');
    await page.getByLabel('Title', { exact: true }).fill('Validation smoke — no inputs');
    await page.getByLabel('Output title', { exact: true }).fill('Should not validate');

    await page.locator('button:has-text("Validate")').click();

    await expect(page.getByText("definition must declare at least one input")).toBeVisible();
  });

  test('Validate reports a single-input definition as valid but warns about correlation value', async ({ page }) => {
    await page.goto('/behavior-intelligence/lab');
    await page.getByLabel('Id', { exact: true }).fill('validation_smoke_single_input');
    await page.getByLabel('Title', { exact: true }).fill('Validation smoke — single input');
    await page.getByLabel('Output title', { exact: true }).fill('Single input pattern');

    await page.locator('button:has-text("Add Input")').click();
    await page.getByLabel('Alias', { exact: true }).first().fill('cpu');
    await page.getByLabel('Metric name', { exact: true }).first().fill('cpu_usage');

    // Added in plain words: "cpu is rising".
    await page.locator('button:has-text("Add all condition")').click();

    await page.locator('button:has-text("Validate")').click();

    await expect(page.getByText('Definition is valid.')).toBeVisible();
    await expect(
      page.getByText(/only one input is really just re-labeling a single analyzer signal/)
    ).toBeVisible();
  });

  test('Validate reports a two-input definition as valid with no warnings', async ({ page }) => {
    await page.goto('/behavior-intelligence/lab');
    await page.getByLabel('Id', { exact: true }).fill('validation_smoke_two_inputs');
    await page.getByLabel('Title', { exact: true }).fill('Validation smoke — two inputs');
    await page.getByLabel('Output title', { exact: true }).fill('Two input pattern');

    await page.locator('button:has-text("Add Input")').click();
    await page.getByLabel('Alias', { exact: true }).first().fill('cpu');
    await page.getByLabel('Metric name', { exact: true }).first().fill('cpu_usage');
    await page.locator('button:has-text("Add Input")').click();
    await page.getByLabel('Alias', { exact: true }).nth(1).fill('memory');
    await page.getByLabel('Metric name', { exact: true }).nth(1).fill('memory_usage');

    // Added in plain words: "cpu is rising".
    await page.locator('button:has-text("Add all condition")').click();

    await page.locator('button:has-text("Validate")').click();

    await expect(page.getByText('Definition is valid.')).toBeVisible();
    await expect(page.getByText(/only one input is really just re-labeling/)).not.toBeVisible();
  });

  test('Validate reports an unresolvable fact path as an error', async ({ page }) => {
    await page.goto('/behavior-intelligence/lab');
    await page.getByLabel('Id', { exact: true }).fill('validation_smoke_bad_fact');
    await page.getByLabel('Title', { exact: true }).fill('Validation smoke — bad fact');
    await page.getByLabel('Output title', { exact: true }).fill('Bad fact pattern');

    await page.locator('button:has-text("Add Input")').click();
    await page.getByLabel('Alias', { exact: true }).first().fill('cpu');
    await page.getByLabel('Metric name', { exact: true }).first().fill('cpu_usage');

    await page.locator('button:has-text("Add all condition")').click();
    await page.getByRole('button', { name: 'Write All condition 1 by hand' }).click();
    await page.getByPlaceholder('cpu.anomaly.present').fill('cpu.not_a_real_fact_path');

    await page.locator('button:has-text("Validate")').click();

    await expect(page.getByText(/condition fact 'cpu\.not_a_real_fact_path'/)).toBeVisible();
  });
});
