// Saves a Jira browser login for the walkthrough recording, so the video can show the ticket in
// Jira itself. Opens a visible browser on the Jira site; log in there as usual. Once the Jira app
// loads, the login is saved and the browser closes.
//
//   node demo/jira_walkthrough/login.cjs <jira-site-url> <state-file>
//
// The state file holds Jira session cookies: keep it outside the repository.

const path = require('path');
const fs = require('fs');
const { chromium } = require(path.join(__dirname, '..', '..', 'frontend', 'node_modules', 'playwright'));

async function main() {
  const [siteUrl, stateFile] = process.argv.slice(2);
  if (!siteUrl || !stateFile) throw new Error('usage: login.cjs <jira-site-url> <state-file>');
  const site = new URL(siteUrl);

  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext({ viewport: { width: 1600, height: 900 } });
  const page = await context.newPage();
  await page.goto(`${site.origin}/jira/your-work`);
  console.log('Log in to Jira in the browser window that just opened (you have 5 minutes).');

  // Logged in once Atlassian has set its session cookie and the browser is back on the Jira site.
  // (The first URL above is the site itself too, before it redirects to the login page.)
  const deadline = Date.now() + 300000;
  for (;;) {
    const cookies = await context.cookies(site.origin);
    const onSite = new URL(page.url()).host === site.host;
    if (onSite && cookies.some((cookie) => cookie.name === 'cloud.session.token')) break;
    if (Date.now() > deadline) throw new Error('timed out waiting for the Jira login');
    await page.waitForTimeout(1000);
  }
  await page.waitForLoadState('networkidle', { timeout: 60000 }).catch(() => {});
  await context.storageState({ path: stateFile });
  fs.chmodSync(stateFile, 0o600);
  await browser.close();
  console.log(`Jira login saved to ${stateFile}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
