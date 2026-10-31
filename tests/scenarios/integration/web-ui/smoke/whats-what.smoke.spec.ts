import { expect, test } from '@playwright/test';
import { expectWebUiPageLoadsCleanly } from '../../shared/smoke';

const pages = [
  { path: '/findings', highlighted: 'Finding', word: 'Evidence badge' },
  { path: '/cases', highlighted: 'Case', word: 'Finding vs case' },
  { path: '/behavior-intelligence', highlighted: 'Finding', word: 'Combined pattern' },
  { path: '/recurring-problems', highlighted: 'Memory', word: 'Recurring problem' },
];

for (const { path, highlighted, word } of pages) {
  test(`What's what? on ${path} explains the page's words and links the glossary`, async ({ page }) => {
    await expectWebUiPageLoadsCleanly(page, path);

    await page.getByRole('button', { name: "What's what?" }).click();

    const dialog = page.getByRole('dialog', { name: "What's what?" });
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('li[aria-current="page"]')).toContainText(highlighted);
    await expect(dialog.getByRole('term').filter({ hasText: word })).toBeVisible();
    await expect(dialog.getByRole('link', { name: /Full glossary/ })).toHaveAttribute('href', /docs\/glossary\.md$/);

    await dialog.getByRole('button', { name: 'Close', exact: true }).last().click();
    await expect(dialog).toBeHidden();
  });
}
