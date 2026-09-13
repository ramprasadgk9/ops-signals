import { test, expect } from '@playwright/test';

/**
 * Covers the "Load Example" buttons — new-user feedback was that a blank form with only
 * tooltips gave no concrete idea of what a finished pattern looks like. These buttons fill the
 * whole form from a real, already-shipped two-input pattern (core.yml's cpu_throttling,
 * latency_and_errors.yml's latency_error_cascade), not invented sample data, so what loads is
 * guaranteed to be a genuinely valid, matchable definition — confirmed by actually clicking
 * Validate afterward rather than just checking the fields got filled.
 */
test.describe('Behavior Lab — load example', () => {
  test('Load Example: CPU + Throttling fills the form with a valid two-input pattern', async ({ page }) => {
    await page.goto('/behavior-intelligence/lab');
    await page.locator('button:has-text("Load Example: CPU + Throttling")').click();

    await expect(page.getByLabel('Id', { exact: true })).toHaveValue('cpu_throttling_example');
    await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Possible CPU throttling');
    await expect(page.getByLabel('Alias', { exact: true }).first()).toHaveValue('cpu');
    await expect(page.getByLabel('Metric name', { exact: true }).first()).toHaveValue('cpu_usage');
    await expect(page.getByLabel('Alias', { exact: true }).nth(1)).toHaveValue('throttling');
    await expect(page.getByLabel('Metric name', { exact: true }).nth(1)).toHaveValue('cpu_throttled_seconds');
    await expect(page.getByPlaceholder('cpu.anomaly.present').first()).toHaveValue('cpu.anomaly.present');

    await page.locator('button:has-text("Validate")').click();
    await expect(page.getByText('Definition is valid.')).toBeVisible();
  });

  test('Load Example: Latency + Errors fills the form with a valid two-input pattern', async ({ page }) => {
    await page.goto('/behavior-intelligence/lab');
    await page.locator('button:has-text("Load Example: Latency + Errors")').click();

    await expect(page.getByLabel('Id', { exact: true })).toHaveValue('latency_error_cascade_example');
    await expect(page.getByLabel('Alias', { exact: true }).first()).toHaveValue('latency');
    await expect(page.getByLabel('Metric name', { exact: true }).first()).toHaveValue('request_latency_p95');
    await expect(page.getByLabel('Alias', { exact: true }).nth(1)).toHaveValue('errors');
    await expect(page.getByLabel('Metric name', { exact: true }).nth(1)).toHaveValue('error_rate');

    await page.locator('button:has-text("Validate")').click();
    await expect(page.getByText('Definition is valid.')).toBeVisible();
  });

  test('loading an example clears a previous Validate result', async ({ page }) => {
    await page.goto('/behavior-intelligence/lab');
    await page.getByLabel('Id', { exact: true }).fill('will_be_replaced');
    await page.getByLabel('Title', { exact: true }).fill('Will be replaced');
    await page.getByLabel('Output title', { exact: true }).fill('Should not validate');
    await page.locator('button:has-text("Validate")').click();
    await expect(page.getByText('definition must declare at least one input')).toBeVisible();

    await page.locator('button:has-text("Load Example: CPU + Throttling")').click();
    await expect(page.getByText('definition must declare at least one input')).not.toBeVisible();
  });
});
