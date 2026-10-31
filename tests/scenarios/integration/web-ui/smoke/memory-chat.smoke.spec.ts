import { expect, test } from '@playwright/test';
import { expectWebUiPageLoadsCleanly } from '../../shared/smoke';

test('Memory Chat / Assistant page loads without a crash', async ({ page }) => {
  await expectWebUiPageLoadsCleanly(page, '/assistant');
});

test('Memory Chat page also loads without a crash at its alternate route', async ({ page }) => {
  await expectWebUiPageLoadsCleanly(page, '/memory-chat');
});

test('Reindex docs help leads to the doc-writing tips and Check new docs', async ({ page }) => {
  await expectWebUiPageLoadsCleanly(page, '/assistant');

  await page.getByRole('button', { name: 'What does Reindex docs do?' }).click();
  await expect(page.getByText('Writing a doc?')).toBeVisible();
  await page.getByRole('button', { name: '6 tips for docs it can answer from' }).click();

  const tips = page.getByRole('dialog', { name: 'Writing docs the assistant can answer from' });
  await expect(tips).toBeVisible();
  await expect(tips.getByRole('listitem')).toHaveCount(6);
  await expect(tips.getByRole('link', { name: /Read the full guide/ })).toHaveAttribute('href', /ask-ops-signals-assistant\.md#writing-docs-the-assistant-can-answer-from$/);

  await tips.getByRole('link', { name: 'Check new docs →' }).click();
  await expect(page).toHaveURL(/\/assistant\/docs-check$/);
  await expect(page.getByText('Check new docs', { exact: true })).toBeVisible();
});
