import { test, expect } from '@playwright/test';

/**
 * Covers starting a pattern from a known one instead of a blank form: a blank builder points at
 * the known patterns, and a template opens with its metrics and conditions filled in, as a valid
 * definition — confirmed by clicking Validate rather than just checking the fields got filled.
 */
test.describe('Behavior Lab — start from a known pattern', () => {
  test('a blank pattern points at the known patterns', async ({ page }) => {
    await page.goto('/behavior-intelligence/lab');
    await page.getByRole('button', { name: 'See known patterns' }).click();

    await expect(page.getByRole('button', { name: 'Close builder' })).not.toBeVisible();
    await expect(page).not.toHaveURL(/builder=/);
    await expect(page.getByText('Start from a known pattern', { exact: true })).toBeInViewport();
  });

  test('a known pattern opens with its conditions in plain words, and is valid', async ({ page }) => {
    await page.goto('/behavior-intelligence?tab=patterns');
    const card = page.locator('article').filter({ has: page.getByRole('heading', { name: 'Consumer falling behind' }) });
    await card.getByRole('button', { name: 'Use this pattern' }).click();

    await expect(page.getByLabel('Id', { exact: true })).toHaveValue('consumer_falling_behind');
    await expect(page.getByRole('combobox', { name: 'What happens' })).toHaveCount(2);
    await expect(page.getByRole('combobox', { name: 'What happens' }).first()).toHaveText('is rising');

    await page.locator('button:has-text("Validate")').click();
    await expect(page.getByText('Definition is valid.')).toBeVisible();
  });
});
