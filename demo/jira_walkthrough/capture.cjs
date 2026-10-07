// Records the "track a case in Jira" walkthrough from a running demo stack with ticketing on:
// a captioned screen recording of the real case page (create the ticket, sync a Jira comment and
// status back, keep the comment as a note, send the resolution to Jira, webhook setup).
// Run through scripts/record_jira_walkthrough.sh, which opens a fresh case and passes its id.
//
//   node demo/jira_walkthrough/capture.cjs <work-dir> <case-id>
//
// The Jira side of the story (a teammate's comment, moving the ticket to In Progress) is made with
// Jira's REST API, using OPS_SIGNALS_JIRA_BASE_URL / _EMAIL / _API_TOKEN from the environment. When
// JIRA_BROWSER_STATE names a saved Jira login (record_jira_walkthrough.sh --login), the video also
// shows the ticket in Jira itself; without it, only Ops Signals is shown.
//
// Writes <work-dir>/walkthrough.webm and <work-dir>/frames/{NN.png,frames.json}. The overlay
// helpers are the same as demo/analyzer_walkthrough/capture.cjs.

const path = require('path');
const fs = require('fs');
const { chromium } = require(path.join(__dirname, '..', '..', 'frontend', 'node_modules', 'playwright'));

const WEB = process.env.DEMO_WEB_URL || 'http://localhost:8080';
const VIEWPORT = { width: 1600, height: 900 };
const JIRA_URL = (process.env.OPS_SIGNALS_JIRA_BASE_URL || '').replace(/\/+$/, '');
const JIRA_AUTH = Buffer.from(`${process.env.OPS_SIGNALS_JIRA_EMAIL || ''}:${process.env.OPS_SIGNALS_JIRA_API_TOKEN || ''}`).toString('base64');
const JIRA_BROWSER_STATE = process.env.JIRA_BROWSER_STATE || '';
const TEAMMATE_COMMENT = 'Rolled checkout-api back to v2.13.2. p95 latency is back to ~180 ms.';

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
    .wrap { width: 1180px; text-align: center; }
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
    // The ticket card is the last thing on the case page, so without room below it the page can't
    // scroll it clear of the caption bar. Blank space under the page, for the recording only.
    if (!target.dataset.demoRoom) {
      target.dataset.demoRoom = '1';
      const room = document.createElement('div');
      room.style.height = '60vh';
      // Inside the outermost painted container, so the space has the app's background, not the body's.
      let host = scroller || document.body;
      for (let node = el.parentElement; node && node !== document.body; node = node.parentElement) {
        if (getComputedStyle(node).backgroundColor !== 'rgba(0, 0, 0, 0)') host = node;
      }
      host.appendChild(room);
    }
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

async function api(method, pathname, body) {
  const response = await fetch(`${WEB}${pathname}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${method} ${pathname}: ${response.status} ${await response.text()}`);
  return response.status === 204 ? null : response.json();
}

async function jira(method, pathname, body) {
  const response = await fetch(`${JIRA_URL}${pathname}`, {
    method,
    headers: { Authorization: `Basic ${JIRA_AUTH}`, Accept: 'application/json', 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`Jira ${method} ${pathname}: ${response.status} ${await response.text()}`);
  return response.status === 204 ? null : response.json();
}

// What a teammate does in Jira while the case is open: comment, then move the ticket along.
async function teammateUpdatesTicket(key) {
  await jira('POST', `/rest/api/3/issue/${key}/comment`, {
    body: { type: 'doc', version: 1, content: [{ type: 'paragraph', content: [{ type: 'text', text: TEAMMATE_COMMENT }] }] },
  });
  const { transitions } = await jira('GET', `/rest/api/3/issue/${key}/transitions`);
  const inProgress = transitions.find((t) => /progress/i.test(t.to?.name || t.name));
  if (!inProgress) throw new Error(`no "In Progress" transition on ${key}: ${transitions.map((t) => t.name).join(', ')}`);
  await jira('POST', `/rest/api/3/issue/${key}/transitions`, { transition: { id: inProgress.id } });
}

async function main() {
  const [workDir, caseId] = process.argv.slice(2);
  if (!workDir || !caseId) throw new Error('usage: capture.cjs <work-dir> <case-id>');
  if (!JIRA_URL || !process.env.OPS_SIGNALS_JIRA_API_TOKEN) throw new Error('OPS_SIGNALS_JIRA_BASE_URL, _EMAIL and _API_TOKEN must be set');
  const showJira = Boolean(JIRA_BROWSER_STATE && fs.existsSync(JIRA_BROWSER_STATE));
  const framesDir = path.join(workDir, 'frames');
  const videoDir = path.join(workDir, 'video');
  fs.mkdirSync(framesDir, { recursive: true });

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 1,
    colorScheme: 'light',
    recordVideo: { dir: videoDir, size: VIEWPORT },
    ...(showJira ? { storageState: JIRA_BROWSER_STATE } : {}),
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
  const ticketCard = () => page.getByText('External Ticketing', { exact: true }).locator('xpath=ancestor::div[contains(@class, "MuiCard-root")][1]');
  const openCase = async () => {
    await page.goto(`${WEB}/cases/${caseId}`);
    await ticketCard().waitFor({ timeout: 20000 });
    await page.mouse.move(800, 450);
    await hold(600);
  };
  const showTicketInJira = async (ticket, title, detail) => {
    await page.goto(ticket.ticket_url, { timeout: 60000 });
    await page.getByText(ticket.display_key).first().waitFor({ timeout: 60000 });
    await hold(2500);
    await caption(page, title, detail);
    await hold(3500);
    await shot(3.5);
  };

  try {
    await page.setContent(
      card({
        kicker: 'Ops Signals · Jira',
        title: 'Track a case in Jira',
        steps: [
          ['Step 1', 'Create the ticket', 'One click from the case. The summary and evidence go with it.'],
          ['Step 2', 'Keep it in sync', 'Comments and status from Jira come back into the case.'],
          ['Step 3', 'Close the loop', 'Resolve the case and the fix is posted to Jira.'],
        ],
      }),
    );
    await shot(4);
    await hold(4000);

    // The case.
    await openCase();
    await caption(page, 'A new case: checkout-api p95 latency shifted after a deploy', 'Every case can have one Jira ticket.');
    await hold(2500);
    await shot(2.5);

    // Step 1: create the ticket.
    await bringIntoView(page, ticketCard(), 220);
    await focus(page, ticketCard());
    await caption(page, '<b>Step 1</b> · External Ticketing → Create Jira Ticket');
    await hold(1200);
    await focus(page, null);
    await clickOn(page, page.getByRole('button', { name: 'Create Jira Ticket' }));
    const keyChip = ticketCard().locator('a.MuiChip-root').first();
    await keyChip.waitFor({ timeout: 30000 });
    const ticket = await api('GET', `/api/cases/${caseId}/ticket`);
    await hold(800);
    // The card grows once the ticket is linked; keep it clear of the caption bar.
    await bringIntoView(page, ticketCard(), 220);
    await focus(page, keyChip.locator('xpath=ancestor::div[contains(@class, "MuiBox-root")][1]'));
    await caption(page, `<b>Step 1 done</b> · ${ticket.display_key} is created in Jira`, 'Created in the background, so a slow Jira never holds up the case.');
    await hold(3000);
    await shot(3);
    await focus(page, null);

    if (showJira) {
      await showTicketInJira(ticket, `The ticket in your Jira project`, 'Title, summary and evidence come from the case.');
    }

    // Step 2: a teammate works the ticket in Jira; Sync Now brings it back.
    await teammateUpdatesTicket(ticket.display_key);
    if (showJira) {
      await page.reload({ timeout: 60000 });
      await page.getByText(TEAMMATE_COMMENT).first().waitFor({ timeout: 60000 });
      await hold(1500);
      await caption(page, '<b>Step 2</b> · A teammate comments in Jira and moves it to In Progress');
      await hold(3500);
      await shot(3.5);
      await openCase();
    } else {
      await caption(page, '<b>Step 2</b> · Meanwhile, a teammate comments in Jira and moves it to In Progress');
      await hold(3000);
    }
    await bringIntoView(page, ticketCard(), 220);
    await caption(page, '<b>Step 2</b> · Sync Now brings the comment and the status back');
    await clickOn(page, page.getByRole('button', { name: /Sync Now/ }));
    const comment = ticketCard().getByText(TEAMMATE_COMMENT);
    await comment.waitFor({ timeout: 30000 });
    await ticketCard().getByText(/In Progress/i).first().waitFor({ timeout: 30000 });
    await hold(800);
    await focus(page, comment.locator('xpath=..'));
    await caption(page, '<b>Step 2 done</b> · The comment and the new status are on the case', 'A Jira webhook can do this automatically. See the end.');
    await hold(3000);
    await shot(3);

    await clickOn(page, ticketCard().getByRole('button', { name: /Add to Notes/ }));
    await ticketCard().getByText('Added to notes').waitFor({ timeout: 15000 });
    await caption(page, '<b>Step 2</b> · + Add to Notes keeps the useful comments in the case', 'They become part of the investigation and what operational memory learns.');
    await hold(3000);
    await shot(3);
    await focus(page, null);

    // Step 3: resolve the case, then send the resolution to Jira.
    await api('PATCH', `/api/cases/${caseId}/resolution`, {
      outcome_status: 'resolved',
      outcome_summary: 'Rolled back to v2.13.2; p95 latency returned to baseline within 5 minutes.',
      corrective_action: 'Roll back the deploy, then batch the catalog lookups before re-releasing.',
      learning_outcome_status: 'confirmed',
      root_cause_category: 'deploy regression',
      resolved_by: 'oncall',
    });
    await openCase();
    await bringIntoView(page, ticketCard(), 220);
    const syncResolution = page.getByRole('button', { name: 'Sync Resolution to Jira' });
    await syncResolution.waitFor({ timeout: 15000 });
    await focus(page, syncResolution);
    await caption(page, '<b>Step 3</b> · Once the case is resolved, send the resolution to Jira');
    await hold(1800);
    await focus(page, null);
    await clickOn(page, syncResolution);
    const synced = ticketCard().getByText(/Resolution (Synced to Jira|Posted) ✓/);
    await synced.waitFor({ timeout: 30000 });
    await hold(800);
    await focus(page, synced);
    await caption(page, '<b>Step 3 done</b> · The cause and the fix are posted on the ticket', 'And the ticket moves to Done when the project allows it.');
    await hold(3000);
    await shot(3);
    await focus(page, null);

    if (showJira) {
      await showTicketInJira(ticket, 'In Jira: the resolution is on the ticket', 'Nobody had to copy it over by hand.');
      await openCase();
      await bringIntoView(page, ticketCard(), 220);
    }

    // Webhooks, for syncing without Sync Now.
    await clickOn(page, page.getByRole('button', { name: /Webhook Setup/ }));
    const dialog = page.getByRole('dialog');
    await dialog.getByText('WEBHOOK TARGET URL').waitFor({ timeout: 10000 });
    await hold(600);
    await caption(page, 'Optional: a Jira webhook syncs comments and status instantly', 'Webhook Setup shows the URL to paste into Jira and the steps.');
    await hold(3500);
    await shot(3.5);
    await clickOn(page, dialog.getByRole('button', { name: 'Close' }));
    await hold(700);

    await page.setContent(
      card({
        kicker: 'Set it up',
        title: 'Turn on Jira ticketing',
        steps: [
          ['Jira', 'Create an API token', 'id.atlassian.com → Security → API tokens.'],
          ['Ops Signals', 'Add the Jira settings', 'Site URL, email, token and project key.'],
          ['Try it', 'Open any case', 'Click Create Jira Ticket.'],
        ],
        footer: 'Every setting is listed in <code>docs/configuration.md</code>.',
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
  }

  fs.writeFileSync(path.join(framesDir, 'frames.json'), JSON.stringify(frames, null, 2));
  console.log(`captured ${frames.length} frames and a video into ${workDir}${showJira ? '' : ' (Jira pages not shown: no saved Jira login)'}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
