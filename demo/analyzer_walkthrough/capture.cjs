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

// Captions, the focus outline and a visible mouse pointer (headless Chromium draws none), installed
// into every document the page loads, including the title cards.
const OVERLAY_SCRIPT = `
  (() => {
    const css = \`
      #demo-caption { position: fixed; left: 0; right: 0; bottom: 0; z-index: 2147483646;
        padding: 16px 28px; background: rgba(17, 24, 39, 0.94); color: #fff; pointer-events: none;
        font: 600 23px/1.35 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
      #demo-caption small { display: block; margin-top: 4px; font-weight: 400; font-size: 17px; color: #cbd5e1; }
      #demo-caption b { color: #fbbf24; }
      .demo-focus { outline: 3px solid #f59e0b !important; outline-offset: 4px; border-radius: 6px; }
      #demo-cursor { position: fixed; z-index: 2147483647; width: 22px; height: 22px; margin: -3px 0 0 -3px;
        pointer-events: none; transition: transform 120ms ease; left: -100px; top: -100px; }
      #demo-cursor.down { transform: scale(0.8); }
      .demo-ripple { position: fixed; z-index: 2147483646; width: 40px; height: 40px; margin: -20px 0 0 -20px;
        border-radius: 50%; border: 3px solid #f59e0b; pointer-events: none; animation: demo-ripple 500ms ease-out forwards; }
      @keyframes demo-ripple { from { transform: scale(0.3); opacity: 1; } to { transform: scale(1.4); opacity: 0; } }
    \`;
    const install = () => {
      if (document.getElementById('demo-cursor')) return;
      const style = document.createElement('style');
      style.textContent = css;
      document.head.appendChild(style);
      const cursor = document.createElement('div');
      cursor.id = 'demo-cursor';
      cursor.innerHTML = '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M3 2l7 19 2.6-7.4L20 11z" fill="#111827" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
      document.body.appendChild(cursor);
      const last = window.__demoPointer;
      if (last) { cursor.style.left = last.x + 'px'; cursor.style.top = last.y + 'px'; }
      document.addEventListener('mousemove', (e) => {
        window.__demoPointer = { x: e.clientX, y: e.clientY };
        cursor.style.left = e.clientX + 'px';
        cursor.style.top = e.clientY + 'px';
      }, true);
      document.addEventListener('mousedown', (e) => {
        cursor.classList.add('down');
        const ripple = document.createElement('div');
        ripple.className = 'demo-ripple';
        ripple.style.left = e.clientX + 'px';
        ripple.style.top = e.clientY + 'px';
        document.body.appendChild(ripple);
        setTimeout(() => ripple.remove(), 600);
      }, true);
      document.addEventListener('mouseup', () => cursor.classList.remove('down'), true);
    };
    if (document.body) install();
    else document.addEventListener('DOMContentLoaded', install);
  })();
`;

function card({ kicker, title, steps, footer }) {
  const escape = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  return `<!doctype html><meta charset="utf-8"><style>
    body { margin: 0; height: 100vh; display: grid; place-items: center; background: #0b1020; color: #fff;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
    .wrap { width: 1040px; text-align: center; }
    .kicker { display: inline-block; padding: 6px 14px; border-radius: 999px; background: #0f766e; font-weight: 800; font-size: 16px; }
    h1 { margin: 22px 0 34px; font-size: 44px; line-height: 1.2; }
    ol { display: grid; grid-template-columns: repeat(${steps.length}, 1fr); gap: 18px; padding: 0; margin: 0; list-style: none; text-align: left; }
    li { padding: 22px; border-radius: 14px; background: #111827; border: 1px solid #1f2937; }
    li b { display: block; color: #fbbf24; font-size: 15px; letter-spacing: 0.04em; text-transform: uppercase; }
    li span { display: block; margin-top: 8px; font-size: 21px; font-weight: 700; }
    li em { display: block; margin-top: 6px; font-style: normal; color: #9ca3af; font-size: 16px; line-height: 1.4; }
    p { margin: 34px 0 0; color: #cbd5e1; font-size: 19px; }
    code { font-family: Menlo, Monaco, Consolas, monospace; color: #e5e7eb; }
  </style><div class="wrap"><span class="kicker">${escape(kicker)}</span><h1>${escape(title)}</h1><ol>${steps
    .map(([label, name, detail]) => `<li><b>${escape(label)}</b><span>${escape(name)}</span><em>${escape(detail)}</em></li>`)
    .join('')}</ol>${footer ? `<p>${footer}</p>` : ''}</div>`;
}

async function caption(page, title, detail) {
  await page.evaluate(
    ([t, d]) => {
      document.getElementById('demo-caption')?.remove();
      const el = document.createElement('div');
      el.id = 'demo-caption';
      el.innerHTML = t;
      if (d) {
        const small = document.createElement('small');
        small.textContent = d;
        el.appendChild(small);
      }
      document.body.appendChild(el);
    },
    [title, detail || ''],
  );
}

async function focus(page, locator) {
  await page.evaluate(() => document.querySelectorAll('.demo-focus').forEach((el) => el.classList.remove('demo-focus')));
  if (locator) await locator.evaluate((el) => el.classList.add('demo-focus'));
}

// Scrolls the element to a comfortable spot above the caption bar.
async function bringIntoView(page, locator, offset = 140) {
  await locator.evaluate((el, top) => {
    let scroller = el.parentElement;
    while (scroller && !(scroller.scrollHeight > scroller.clientHeight && /(auto|scroll)/.test(getComputedStyle(scroller).overflowY))) {
      scroller = scroller.parentElement;
    }
    const target = scroller || document.scrollingElement;
    const delta = el.getBoundingClientRect().top - (scroller ? scroller.getBoundingClientRect().top : 0) - top;
    target.scrollBy({ top: delta, behavior: 'smooth' });
  }, offset);
  await page.waitForTimeout(900);
}

async function pointAt(page, locator) {
  const box = await locator.boundingBox();
  if (!box) throw new Error('element to point at is not visible');
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 25 });
  await page.waitForTimeout(250);
}

async function clickOn(page, locator) {
  await pointAt(page, locator);
  await page.mouse.down();
  await page.waitForTimeout(90);
  await page.mouse.up();
}

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
