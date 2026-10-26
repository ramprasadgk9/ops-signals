import { expect, test, type Page } from '@playwright/test';

// The web UI's own sign-in with the local test provider (backend/devtools/test_sign_in_provider.py), end
// to end: sign-in page, the provider's account page, back signed in with the account's role, sign out.
// Needs a web UI whose backend runs OPS_SIGNALS_AUTH_MODE=oidc against the test provider, e.g.
// OPS_SIGNALS_TEST_SIGN_IN=true with scripts/run_all.sh; set OPS_SIGNALS_OIDC_WEB_UI_URL to its address.
const BASE = process.env.OPS_SIGNALS_OIDC_WEB_UI_URL;
test.skip(!BASE, 'Set OPS_SIGNALS_OIDC_WEB_UI_URL to a web UI using the local test sign-in provider.');

async function signInAs(page: Page, account: string, path = '/findings') {
  await page.goto(`${BASE}${path}`);
  await page.getByRole('link', { name: 'Sign in with test accounts' }).click();
  await expect(page.getByText('For trying Ops Signals on this computer only.')).toBeVisible();
  await page.getByRole('button', { name: new RegExp(`^${account}@example.com`) }).click();
}

test('a Viewer signs in, gets the Viewer menu, and signs out', async ({ page }) => {
  await signInAs(page, 'sam');
  await expect(page).toHaveURL(`${BASE}/findings`);
  await expect(page.getByText('sam · Viewer')).toBeVisible({ timeout: 20_000 });
  const menu = page.getByRole('complementary');
  await expect(menu.getByRole('link', { name: 'Findings' })).toBeVisible();
  await expect(menu.getByRole('link', { name: 'Settings', exact: true })).toHaveCount(0);

  await page.getByRole('button', { name: 'Signed in as sam@example.com, Viewer' }).click();
  await expect(page.getByText('Session ends in')).toBeVisible();
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByText("You're signed out of Ops Signals.")).toBeVisible();

  await page.goto(`${BASE}/findings`);
  await expect(page.getByRole('link', { name: 'Sign in with test accounts' })).toBeVisible();
});

test('an Admin signs in and Setup check says the test provider is on', async ({ page }) => {
  await signInAs(page, 'ada', '/setup-check');
  await expect(page.getByText('ada · Admin')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('Signed in with the local test provider: for trying sign-in on this computer only.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Test sign-in' })).toBeVisible();
});

test('someone whose groups did not come through carries on as a Viewer', async ({ page }) => {
  await signInAs(page, 'lee', '/cases');
  await expect(page.getByText("Signed in, but your groups didn't come through")).toBeVisible();
  await page.getByRole('link', { name: 'Continue as Viewer' }).click();
  await expect(page.getByText('lee · Viewer')).toBeVisible({ timeout: 20_000 });
});
