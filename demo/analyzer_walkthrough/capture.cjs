// Records the "add an analyzer" walkthrough from a running demo stack (docker-compose.demo.yml):
// a captioned screen recording of the real Add Analyzer page (save a draft, test it on lab data,
// review the YAML, promote), which that page plays from its "Watch how" button.
// Run through scripts/record_analyzer_walkthrough.sh, which copies it into frontend/public.
//
//   node demo/analyzer_walkthrough/capture.cjs <work-dir>
//
// Writes <work-dir>/walkthrough.webm and <work-dir>/frames/{NN.png,frames.json}. The analyzer it
// creates is deleted again at the end, so the demo is left as it was.
//
// Uses the Playwright + Chromium that the frontend's integration tests already install.

const path = require('path');
const fs = require('fs');
const { chromium } = require(path.join(__dirname, '..', '..', 'frontend', 'node_modules', 'playwright'));

const WEB = process.env.DEMO_WEB_URL || 'http://localhost:8080';
const VIEWPORT = { width: 1280, height: 800 };
const ANALYZER_ID = 'weekly_traffic_pattern';
const DISPLAY_NAME = 'Weekly Traffic Pattern';

const { OVERLAY_SCRIPT, card, caption, focus, bringIntoView, pointAt, clickOn } = require('../walkthrough_kit.cjs');

async function typeInto(page, locator, text) {
  await clickOn(page, locator);
  await locator.press('ControlOrMeta+a');
  await locator.press('Backspace');
  await locator.pressSequentially(text, { delay: 70 });
}

async function deleteAnalyzer() {
  await fetch(`${WEB}/api/analyzer-labs/analyzers/${ANALYZER_ID}?delete_code_file=true`, { method: 'DELETE' }).catch(() => {});
}

async function main() {
  const [workDir] = process.argv.slice(2);
  if (!workDir) throw new Error('usage: capture.cjs <work-dir>');
  const framesDir = path.join(workDir, 'frames');
  const videoDir = path.join(workDir, 'video');
  fs.mkdirSync(framesDir, { recursive: true });

  await deleteAnalyzer();

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 1,
    colorScheme: 'light',
    recordVideo: { dir: videoDir, size: VIEWPORT },
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

  try {
    // Title card.
    await page.setContent(
      card({
        kicker: 'Ops Signals · Analyzer Workbench',
        title: 'Add your own analyzer in three steps',
        steps: [
          ['Step 1', 'Save a draft', 'Validated automatically. Stored in Postgres, YAML untouched.'],
          ['Step 2 · optional', 'Test on lab data', 'Would the router pick it for a known behavior?'],
          ['Step 3', 'Promote', 'Review the YAML, then register it with the router.'],
        ],
      }),
    );
    await shot(4);
    await hold(4000);

    // The page, and where to start.
    await page.goto(`${WEB}/experiments/add-analyzer`);
    await page.waitForSelector('text=Analyzer Setup Flow', { timeout: 20000 });
    await page.mouse.move(640, 400);
    await hold(800);
    await bringIntoView(page, page.locator('text=Start here').first(), 40);
    await caption(page, 'Start on <b>Experiments → Add Analyzer</b>', 'The Setup Flow card always shows the next step.');
    await focus(page, page.getByRole('alert').first());
    await hold(2500);
    await shot(3);

    // Step 1: name it and save the draft.
    await focus(page, null);
    const addButton = page.getByRole('button', { name: 'Add Analyzer' });
    await caption(page, '<b>Step 1</b> · Click Add Analyzer and choose a path');
    await clickOn(page, addButton);
    await page.waitForSelector('text=What are you adding?');
    await hold(1500);
    await shot(3);
    await clickOn(page, page.getByRole('button', { name: /I have Python code/ }));
    await page.waitForSelector('text=Change path');
    await hold(800);
    await caption(page, '<b>Step 1</b> · Give it an ID and a name', 'A template fills in the routing rules. Tune them later if you need to.');
    await typeInto(page, page.getByLabel('Analyzer ID'), ANALYZER_ID);
    await hold(300);
    await typeInto(page, page.getByLabel('Display Name'), DISPLAY_NAME);
    await hold(1200);
    await shot(3.5);

    const profiles = page.locator('label', { hasText: 'Supported Profiles' }).locator('xpath=..');
    await bringIntoView(page, profiles, 160);
    await focus(page, profiles);
    await caption(page, '<b>Step 1</b> · Supported profiles decide when the router picks it', 'This one is for repeating, seasonal traffic.');
    await hold(3000);
    await shot(3);
    await focus(page, null);

    const saveButton = page.getByRole('button', { name: 'Save Draft', exact: true });
    await bringIntoView(page, saveButton, 260);
    await caption(page, '<b>Step 1</b> · Save Draft', 'Saving validates the definition. Nothing goes live yet.');
    await clickOn(page, saveButton);
    await page.getByText('Draft saved to Postgres').waitFor({ timeout: 15000 });
    // The drawer's own progress box sits clear of the caption bar; the success alert below it doesn't.
    const progress = page.getByText('This popup progress').locator('xpath=..');
    await bringIntoView(page, progress, 330);
    await focus(page, progress);
    await caption(page, '<b>Step 1 done</b> · The draft is saved and validated', 'Stored in Postgres only. The analyzer YAML is unchanged.');
    await hold(2500);
    await shot(3.5);
    await focus(page, null);
    await page.keyboard.press('Escape');
    await hold(900);

    // Step 2: test on lab data.
    const labSelect = page.locator('label', { hasText: /^Lab Data$/ }).locator('xpath=..').getByRole('combobox');
    await bringIntoView(page, page.getByText('Test With Lab Data', { exact: true }), 90);
    await caption(page, '<b>Step 2</b> (optional) · Test with lab data', 'Pick a generated behavior and ask the router whether it would recommend this analyzer.');
    await hold(1500);
    await clickOn(page, labSelect);
    await hold(700);
    await clickOn(page, page.getByRole('option', { name: 'STUMPY motif generated data' }));
    await hold(600);
    await clickOn(page, page.getByRole('button', { name: 'Run on Lab Data' }));
    await page.getByText(/Completed with/).waitFor({ timeout: 20000 });
    await hold(800);
    // A finished test collapses to a one-line summary; Review reopens it with the reasons.
    await bringIntoView(page, page.getByText('Test With Lab Data', { exact: true }), 120);
    await clickOn(page, page.getByRole('button', { name: 'Review', exact: true }));
    const resultBox = page.getByRole('alert').filter({ hasText: 'Recommendation:' });
    await resultBox.waitFor({ timeout: 10000 });
    await hold(500);
    await bringIntoView(page, resultBox, 260);
    await focus(page, resultBox);
    await caption(page, '<b>Step 2 done</b> · The router recommends it for repeating-pattern data', 'The result shows the score and the reasons behind it.');
    await hold(3500);
    await shot(4);
    await focus(page, null);

    // Step 3: review the YAML, then promote.
    const advanced = page.getByRole('button', { name: 'Advanced: view saved state' });
    await bringIntoView(page, page.getByText('Current Analyzer', { exact: true }), 90);
    await caption(page, '<b>Step 3</b> · Review the YAML before promoting');
    await hold(1000);
    await clickOn(page, advanced);
    const yaml = page.getByText('YAML preview', { exact: true });
    await yaml.waitFor({ timeout: 10000 });
    await page.waitForFunction((id) => [...document.querySelectorAll('textarea')].some((t) => t.value.includes(id)), ANALYZER_ID, { timeout: 10000 });
    await hold(500);
    const yamlField = yaml.locator('xpath=following-sibling::*[1]');
    await bringIntoView(page, yaml, 120);
    await focus(page, yamlField);
    await caption(page, '<b>Step 3</b> · This is exactly what Promote registers', 'The same definition you would otherwise write into the analyzer YAML by hand.');
    await hold(3500);
    await shot(4);
    await focus(page, null);

    const promote = page.getByRole('button', { name: 'Promote Analyzer' });
    await bringIntoView(page, promote, 260);
    await caption(page, '<b>Step 3</b> · Promote Analyzer');
    await hold(800);
    await clickOn(page, promote);
    const added = page.getByText('Analyzer added', { exact: true });
    await added.waitFor({ timeout: 15000 });
    await bringIntoView(page, added, 120);
    await focus(page, added.locator('xpath=..'));
    await caption(page, `<b>Live</b> · ${ANALYZER_ID} is registered with the router`, 'Next: add backend support to get a Python file for your analyze() logic.');
    await hold(1500);
    await pointAt(page, page.getByRole('button', { name: 'Add backend execution support' }).first());
    await hold(2500);
    await shot(4.5);

    // Closing card.
    await page.setContent(
      card({
        kicker: 'What next',
        title: 'Make it produce findings',
        steps: [
          ['Python', 'Add backend support', 'You get a starter file. Fill in analyze().'],
          ['Hosted model', 'Point at your API', 'No Python needed. Ops Signals calls your service.'],
          ['Check', 'Run the Execution Test', 'Confirm it returns signals on real data.'],
        ],
        footer: 'Close this video and click <code>Add Analyzer</code> to try it.',
      }),
    );
    await hold(4500);
    await shot(4.5);
  } catch (error) {
    await page.screenshot({ path: path.join(workDir, 'failed-at.png') }).catch(() => {});
    throw error;
  } finally {
    const video = page.video();
    await context.close();
    if (video) await video.saveAs(path.join(workDir, 'walkthrough.webm'));
    await browser.close();
    await deleteAnalyzer();
  }

  fs.writeFileSync(path.join(framesDir, 'frames.json'), JSON.stringify(frames, null, 2));
  console.log(`captured ${frames.length} frames and a video into ${workDir}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
