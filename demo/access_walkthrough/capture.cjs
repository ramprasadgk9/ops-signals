// Records the "who can use Ops Signals" walkthrough Setup check → Login plays: the three steps of
// docs/access.md on a real install. Run through scripts/record_access_walkthrough.sh, which starts a
// sandbox with one web UI per step (no token, a token, company sign-in) and a throwaway Keycloak.
//
//   OPEN_URL=… TOKEN_URL=… SIGNIN_URL=… KEYCLOAK_URL=… TO_SIGN_IN=… node demo/access_walkthrough/capture.cjs <work-dir>
//
// Writes <work-dir>/walkthrough.webm and <work-dir>/frames/{NN.png,frames.json}. The token and the
// client secret are never on screen: the server steps are shown as cards with placeholders.

const path = require('path');
const fs = require('fs');
const { execSync } = require('child_process');
const { chromium } = require(path.join(__dirname, '..', '..', 'frontend', 'node_modules', 'playwright'));
const { OVERLAY_SCRIPT, card, caption, focus, bringIntoView, pointAt, clickOn } = require('../walkthrough_kit.cjs');

const OPEN = process.env.OPEN_URL || 'http://localhost:5187';
const TOKEN = process.env.TOKEN_URL || 'http://localhost:5188';
const SIGNIN = process.env.SIGNIN_URL || TOKEN;
// Moves the web UI at TOKEN_URL to the sign-in backend (SIGNIN_URL is the same address).
const TO_SIGN_IN = process.env.TO_SIGN_IN || '';
const KEYCLOAK = process.env.KEYCLOAK_URL || 'http://127.0.0.1:8181';
const VIEWPORT = { width: 1280, height: 800 };

async function main() {
  const [workDir] = process.argv.slice(2);
  if (!workDir) throw new Error('usage: capture.cjs <work-dir>');
  const framesDir = path.join(workDir, 'frames');
  fs.mkdirSync(framesDir, { recursive: true });

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 1,
    colorScheme: 'light',
    recordVideo: { dir: path.join(workDir, 'video'), size: VIEWPORT },
  });
  await context.addInitScript(OVERLAY_SCRIPT);
  const page = await context.newPage();

  let index = 0;
  const frames = [];
  const shot = async (seconds) => {
    const file = path.join(framesDir, `${String(index++).padStart(2, '0')}.png`);
    await page.screenshot({ path: file });
    frames.push({ file: path.basename(file), seconds });
  };
  const hold = (ms) => page.waitForTimeout(ms);
  let movedToSignIn = !TO_SIGN_IN;
  const moveToSignIn = () => {
    if (movedToSignIn) return;
    execSync(TO_SIGN_IN, { stdio: 'inherit' });
    movedToSignIn = true;
  };
  const loginRegion = () => page.getByRole('region', { name: 'Recommended' });
  const steps = () => loginRegion().getByRole('list', { name: 'Steps to control who can use Ops Signals' });
  const openSetupCheck = async (base) => {
    await page.goto(`${base}/setup-check`);
    await steps().waitFor({ timeout: 30_000 });
    await bringIntoView(page, steps(), 120);
  };
  const typeSlowly = async (locator, text) => {
    await clickOn(page, locator);
    await locator.pressSequentially(text, { delay: 70 });
  };
  const keycloakSignIn = async (user, password) => {
    const username = page.locator('#username');
    await username.waitFor({ timeout: 20_000 });
    await typeSlowly(username, user);
    await typeSlowly(page.locator('#password'), password);
    await clickOn(page, page.locator('#kc-login'));
  };

  try {
    // Title card
    await page.setContent(
      card({
        kicker: 'Ops Signals · Who can use it',
        title: 'Lock it down in three steps',
        steps: [
          ['Step 1', 'Lock the API', 'One command on the server. A minute.'],
          ['Step 2', 'Give people roles', 'Grafana, your company login, or a sign-in proxy.'],
          ['Step 3', 'Check it', 'Setup check turns green. A Viewer sees the locks.'],
        ],
        footer: 'Recorded on a throwaway install. Each step says where it happens.',
      }),
    );
    await shot(4);
    await hold(4500);

    // Out of the box: open to everyone
    await page.goto(`${OPEN}/`);
    const chip = page.getByRole('button', { name: 'Not signed in · everyone can change things' });
    await chip.waitFor({ timeout: 30_000 });
    await caption(page, '<b>Out of the box</b>, anyone who can reach Ops Signals can see and change everything.', 'The chip at the top right says so. Click it for what to do.');
    await focus(page, chip);
    await pointAt(page, chip);
    await hold(3500);
    await shot(4);
    await clickOn(page, chip);
    await hold(1800);
    await clickOn(page, page.getByRole('link', { name: 'Set up sign-in on Setup check' }));
    await steps().waitFor({ timeout: 30_000 });
    await bringIntoView(page, steps(), 120);

    // Step 1
    await caption(page, '<b>Setup check → Login</b> shows the three steps and the one you are on.', 'Here: step 1, lock the API.');
    await focus(page, steps());
    await hold(4000);
    await shot(4);
    await clickOn(page, loginRegion().getByRole('button', { name: 'Lock the API · 1 min: Login' }));
    const command = loginRegion().getByText(/openssl rand -hex 32/);
    await command.waitFor();
    await caption(page, '<b>Step 1 · on the server:</b> run this in the folder with your .env, then restart.', 'It makes a token and saves it. Docker Compose hands it to the backend and the web UI.');
    await focus(page, command);
    await hold(6000);
    await shot(6);
    await focus(page, null);

    await page.setContent(
      card({
        kicker: 'Step 1 · Server',
        title: 'Run it, restart, check again',
        steps: [
          ['Server', 'echo "OPS_SIGNALS_API_TOKEN=…" >> .env', 'Makes a token and saves it.'],
          ['Server', 'docker compose … up -d', 'Restart. The web UI adds the token for you.'],
          ['Ops Signals', 'Check again', 'The Login row moves to step 2.'],
        ],
      }),
    );
    await hold(4500);
    await shot(4);

    // Step 2: token on, nobody signs in
    await openSetupCheck(TOKEN);
    await caption(page, '<b>API locked:</b> step 1 is ticked.', 'But nobody signs in to the web UI yet, so everyone using it can still change everything.');
    await focus(page, steps());
    await hold(4500);
    await shot(4);
    await clickOn(page, loginRegion().getByRole('button', { name: 'Choose how people sign in' }));
    const grafana = page.getByRole('region', { name: 'Grafana plugin' });
    const company = page.getByRole('region', { name: 'Web UI · company login' });
    const proxy = page.getByRole('region', { name: 'Web UI · sign-in proxy' });
    await grafana.waitFor();
    await bringIntoView(page, grafana, 170);
    await caption(page, '<b>Step 2:</b> pick how your team opens Ops Signals.', 'Each step is tagged with where it happens: Grafana, your company login, the server, or here.');
    await hold(4500);
    await shot(4);
    await caption(page, '<b>Using Grafana?</b> Paste the token on the plugin\'s Configuration page.', 'Connect through: Grafana. Grafana\'s own Viewer, Editor and Admin roles then apply.');
    await focus(page, grafana);
    await pointAt(page, grafana);
    await hold(5000);
    await shot(5);
    await caption(page, '<b>Web UI with your company login:</b> register a web app there, with this redirect address.', 'That happens in your company\'s login system, outside Ops Signals. Your identity team can do it.');
    await focus(page, company);
    await pointAt(page, company.getByRole('button', { name: 'Copy' }));
    await hold(5500);
    await shot(5);
    await caption(page, '<b>Already run a sign-in proxy?</b> Make it the only way in, and let it pass the user on.');
    await focus(page, proxy);
    await pointAt(page, proxy);
    await hold(3500);
    await focus(page, null);
    await clickOn(page, company.getByRole('button', { name: 'How to set up company sign-in' }));
    const dialog = page.getByRole('dialog', { name: 'Set up company sign-in' });
    await dialog.waitFor();
    await caption(page, 'Every step, with the settings to copy.');
    await hold(4500);
    await shot(4);
    await page.keyboard.press('Escape');
    await hold(600);

    // Company login: the app registered in a throwaway Keycloak
    try {
      await page.goto(`${KEYCLOAK}/admin/master/console/#/acme/clients`);
      await page.locator('#username').waitFor({ timeout: 20_000 });
      await caption(page, '<b>Company login</b> (here a throwaway Keycloak): sign in to its admin console.');
      moveToSignIn();
      await keycloakSignIn('admin', 'admin');
      const app = page.getByRole('link', { name: 'ops-signals', exact: true });
      await app.waitFor({ timeout: 30_000 });
      await caption(page, '<b>Company login:</b> the app registered for Ops Signals.');
      await focus(page, app);
      await hold(2500);
      await clickOn(page, app);
      const redirect = page.locator('input[value$="/api/auth/callback"]').first();
      await redirect.waitFor({ timeout: 20_000 });
      await bringIntoView(page, redirect, 260);
      await caption(page, '<b>Company login:</b> its redirect address is the one Setup check gave you.', 'Add a groups claim on the same app, and note the issuer, client ID and secret.');
      await focus(page, redirect);
      await pointAt(page, redirect);
      await hold(5500);
      await shot(5);
    } catch (error) {
      console.warn(`Skipped the Keycloak console: ${error.message}`);
    }

    moveToSignIn();

    await page.setContent(
      card({
        kicker: 'Step 2 · Server',
        title: 'Tell Ops Signals about your company login',
        steps: [
          ['Server', 'Add six settings to .env', 'Issuer, client ID and secret, and the groups for Editor and Admin.'],
          ['Server', 'Restart', 'Everyone else who signs in is a Viewer.'],
          ['Ops Signals', 'Test sign-in', 'Setup check → Login, then sign in in the new tab.'],
        ],
      }),
    );
    await hold(5000);
    await shot(5);

    // Step 3: company sign-in on
    await page.goto(`${SIGNIN}/`);
    const signIn = page.getByRole('link', { name: /^Sign in with / });
    await signIn.waitFor({ timeout: 30_000 });
    await caption(page, 'Now people sign in with their company account.');
    await focus(page, signIn);
    await hold(2500);
    await shot(3);
    await clickOn(page, signIn);
    await keycloakSignIn('john', 'Passw0rd-john');
    const john = page.getByRole('button', { name: /^Signed in as john/ });
    await john.waitFor({ timeout: 30_000 });
    await caption(page, '<b>john is an Admin</b>, because of his group in the company login.');
    await focus(page, john);
    await pointAt(page, john);
    await hold(3500);
    await shot(3);
    await focus(page, null);

    await openSetupCheck(SIGNIN);
    const done = loginRegion().getByRole('listitem', { name: 'Step 3, Check it: done' });
    await done.waitFor({ timeout: 30_000 });
    await caption(page, '<b>Step 3:</b> Login is green, with all three steps ticked.', 'It names who you are and the group that gave your role.');
    await focus(page, steps());
    await hold(5500);
    await shot(5);
    await focus(page, null);

    // The proof: a Viewer
    await clickOn(page, john);
    // Let the menu finish opening, or the pointer aims at where the button is still moving to.
    await hold(1000);
    await caption(page, 'Sign out, and sign in as someone else.');
    await hold(1200);
    // Signing out ends the company login's session too, without a second question.
    await clickOn(page, page.getByRole('button', { name: 'Sign out' }));
    await page.waitForURL('**/signed-out', { timeout: 20_000 });
    const again = page.getByRole('link', { name: /Sign in/ }).first();
    await again.waitFor({ timeout: 30_000 });
    await clickOn(page, again);
    await keycloakSignIn('vic', 'Passw0rd-vic');
    await page.getByRole('button', { name: /^Signed in as vic/ }).waitFor({ timeout: 30_000 });
    await page.goto(`${SIGNIN}/validate-data`);
    const closed = page.getByText(/is for Editors/).first();
    await closed.waitFor({ timeout: 30_000 });
    await caption(page, '<b>The proof:</b> vic is a Viewer.', 'Pages for Editors and Admins are closed and say whom to ask. The backend refuses the same requests.');
    await focus(page, closed);
    await hold(5500);
    await shot(5);
    await focus(page, null);

    await page.setContent(
      card({
        kicker: 'That\'s it',
        title: 'Your next step is always on Setup check → Login',
        steps: [
          ['Read', 'docs/access.md', 'The same three steps, on one page.'],
          ['Roles', 'Who can do what', 'One table: Viewer, Editor, Admin.'],
          ['Try first', 'try_keycloak_sign_in.sh', 'A throwaway login with a Viewer, an Editor and an Admin.'],
        ],
      }),
    );
    await hold(5000);
    await shot(5);
  } catch (error) {
    await page.screenshot({ path: path.join(workDir, 'failed-at.png') }).catch(() => {});
    throw error;
  } finally {
    const video = page.video();
    await context.close();
    if (video) await video.saveAs(path.join(workDir, 'walkthrough.webm'));
    await browser.close();
  }

  fs.writeFileSync(path.join(framesDir, 'frames.json'), JSON.stringify(frames, null, 2));
  console.log(`captured ${frames.length} frames and a video into ${workDir}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
