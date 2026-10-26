import { test, expect, type Page } from '@playwright/test';
import { env } from '../../shared/env';
import { makeRunId, seedFinding, createCaseFromFinding, cleanupRun } from '../../shared/db';

/**
 * The Service filter on Findings and Cases (frontend/src/components/ServiceFilterField.tsx): a
 * searchable dropdown kept in the URL as ?service=. Seeds two findings on two services unique to
 * this run, with a case for each, so the dev data around them doesn't matter.
 */
const serviceField = (page: Page) => page.getByRole('main').getByRole('combobox', { name: 'Service' });

async function pickService(page: Page, service: string) {
  await serviceField(page).click();
  await serviceField(page).fill(service);
  await page.getByRole('option', { name: new RegExp(service) }).click();
}

// A seeded finding has no evidence, so it lands in the folded "Context only" list.
async function openContextOnly(page: Page) {
  const toggle = page.getByRole('button', { name: /Context only/ });
  if ((await toggle.getAttribute('aria-expanded')) === 'false') await toggle.click();
}

test('Findings and Cases filter by service and keep it in the URL', async ({ page }) => {
  const runId = makeRunId('service-filter');
  const payments = `payments-${runId}`;
  const checkout = `checkout-${runId}`;
  const paymentsTitle = `Integration suite payments case ${runId}`;
  const checkoutTitle = `Integration suite checkout case ${runId}`;
  const paymentsFindingId = await seedFinding({ runId, service: payments, metricName: 'error_rate', title: paymentsTitle });
  const checkoutFindingId = await seedFinding({ runId, service: checkout, metricName: 'latency', title: checkoutTitle });
  await createCaseFromFinding(env.webUiBackendUrl, paymentsFindingId);
  await createCaseFromFinding(env.webUiBackendUrl, checkoutFindingId);

  try {
    // Findings: pick a service from the dropdown.
    await page.goto('/findings');
    await expect(page.getByRole('heading', { name: 'Findings', exact: true })).toBeVisible({ timeout: 20_000 });
    await pickService(page, payments);
    await expect(page).toHaveURL(new RegExp(`service=${payments}`));
    await openContextOnly(page);
    await expect(page.getByRole('main').getByText(payments).first()).toBeVisible();
    await expect(page.getByRole('main').getByText(checkout)).toHaveCount(0);

    // A shared link opens already filtered; "Show all services" clears it.
    await page.goto(`/findings?service=${checkout}`);
    await expect(serviceField(page)).toHaveValue(checkout);
    await openContextOnly(page);
    await expect(page.getByRole('main').getByText(checkout).first()).toBeVisible();
    await expect(page.getByRole('main').getByText(payments)).toHaveCount(0);
    await page.getByRole('button', { name: 'Show all services' }).click();
    await expect(page).not.toHaveURL(/service=/);

    // Cases: same dropdown, the list narrows to that service's case.
    await page.goto('/cases?tab=all');
    await pickService(page, payments);
    await expect(page).toHaveURL(new RegExp(`service=${payments}`));
    await expect(page.getByRole('link', { name: paymentsTitle, exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: checkoutTitle, exact: true })).toHaveCount(0);

    await page.goto(`/cases?tab=all&service=${checkout}`);
    await expect(page.getByRole('link', { name: checkoutTitle, exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: paymentsTitle, exact: true })).toHaveCount(0);
  } finally {
    await cleanupRun({ runId, findingId: [paymentsFindingId, checkoutFindingId] });
  }
});
