// Captures the README demo GIF's frames from a running demo stack (docker-compose.demo.yml).
// Run through scripts/record_demo_gif.sh, which also assembles the GIF.
//
//   node demo/gif/capture.cjs <frames-dir> <seeder-log-file>
//
// Uses the Playwright + Chromium that the frontend's integration tests already install.

const path = require('path');
const fs = require('fs');
const { chromium } = require(path.join(__dirname, '..', '..', 'frontend', 'node_modules', 'playwright'));

const WEB = process.env.DEMO_WEB_URL || 'http://localhost:8080';
const SLACK = process.env.DEMO_SLACK_SINK_URL || 'http://localhost:8090';
const PROM = process.env.DEMO_PROMETHEUS_URL || 'http://localhost:9091';
const VIEWPORT = { width: 1280, height: 800 };

const CAPTION_CSS = `
  #demo-caption { position: fixed; left: 0; right: 0; bottom: 0; z-index: 2147483647;
    padding: 18px 28px; background: rgba(17, 24, 39, 0.94); color: #fff;
    font: 600 24px/1.35 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
  #demo-caption small { display: block; margin-top: 4px; font-weight: 400; font-size: 17px; color: #cbd5e1; }
  .demo-focus { outline: 3px solid #f59e0b; outline-offset: 6px; border-radius: 4px;
    background: rgba(245, 158, 11, 0.10); }
`;

async function caption(page, title, detail) {
  await page.addStyleTag({ content: CAPTION_CSS });
  await page.evaluate(
    ([t, d]) => {
      document.getElementById('demo-caption')?.remove();
      const el = document.createElement('div');
      el.id = 'demo-caption';
      el.textContent = t;
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

function card(lines, { title, footer }) {
  const escape = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  return `<!doctype html><meta charset="utf-8"><style>
    body { margin: 0; height: 100vh; display: grid; place-items: center; background: #0b1020;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
    .term { width: 1120px; border-radius: 12px; background: #111827; overflow: hidden; }
    .bar { display: flex; gap: 8px; padding: 14px 16px; background: #1f2937; }
    .bar i { width: 12px; height: 12px; border-radius: 50%; background: #ef4444; }
    .bar i:nth-child(2) { background: #f59e0b; } .bar i:nth-child(3) { background: #22c55e; }
    pre { margin: 0; padding: 22px 26px 28px; color: #e5e7eb; font: 17px/1.6 Menlo, Monaco, Consolas, monospace; white-space: pre-wrap; }
    .cmd { color: #fff; font-weight: 700; } .dim { color: #9ca3af; } .ok { color: #86efac; }
    h1 { margin: 0 0 22px; color: #fff; font-size: 34px; text-align: center; }
    p { color: #cbd5e1; font-size: 20px; text-align: center; margin: 22px 0 0; }
  </style><div>${title ? `<h1>${escape(title)}</h1>` : ''}<div class="term"><div class="bar"><i></i><i></i><i></i></div><pre>${lines
    .map(([cls, text]) => `<span class="${cls}">${escape(text)}</span>`)
    .join('\n')}</pre></div>${footer ? `<p>${escape(footer)}</p>` : ''}</div>`;
}

async function focusSlackBlock(page, heading) {
  await page.evaluate((h) => {
    document.querySelectorAll('.demo-focus').forEach((el) => el.classList.remove('demo-focus'));
    const block = [...document.querySelectorAll('.block')].find((el) => el.textContent.trim().includes(h));
    block?.classList.add('demo-focus');
  }, heading);
}

async function main() {
  const [framesDir, seederLogPath] = process.argv.slice(2);
  if (!framesDir || !seederLogPath) throw new Error('usage: capture.cjs <frames-dir> <seeder-log-file>');
  fs.mkdirSync(framesDir, { recursive: true });

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: VIEWPORT, deviceScaleFactor: 1, colorScheme: 'light' });
  let index = 0;
  const frames = [];
  const shot = async (seconds) => {
    const file = path.join(framesDir, `${String(index++).padStart(2, '0')}.png`);
    await page.screenshot({ path: file });
    frames.push({ file: path.basename(file), seconds });
  };

  // 1. The command, and what the seeder actually printed.
  const seeded = fs
    .readFileSync(seederLogPath, 'utf8')
    .split('\n')
    .map((line) => line.replace(/^demo-seeder:\s*/, '').trim())
    .filter((line) => line && !line.startsWith('waiting') && !line.startsWith('Ops Signals UI') && !line.startsWith('Slack messages'));
  await page.setContent(
    card(
      [
        ['cmd', '$ docker compose -f docker-compose.demo.yml up'],
        ['dim', ''],
        ...seeded.map((line) => ['ok', `✔ ${line}`]),
      ],
      { title: 'Ops Signals, five-minute demo' },
    ),
  );
  await shot(4.5);

  // 2. The incident in Prometheus.
  await page.goto(`${PROM}/graph?g0.expr=request_latency_p95&g0.tab=0&g0.range_input=6h`);
  await page.waitForSelector('canvas, .graph-legend, [class*=legend]', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(2000);
  await caption(page, 'checkout-api p95 latency jumps from ~180ms to ~320ms', 'A few minutes after deploy v2.14.0. A Prometheus threshold alert fires.');
  await shot(4);

  // 3. The enriched alert, one section at a time.
  await page.goto(SLACK);
  await page.waitForSelector('.msg', { timeout: 15000 });
  await caption(page, 'Ops Signals enriches the alert before anyone opens a dashboard', 'Posted to Slack (shown here in the demo’s Slack sink)');
  await shot(3);
  const steps = [
    ['What happened', '📈 What happened: the analyzers found a baseline shift and when it started'],
    ['What changed', '🚀 What changed: it started 4 minutes after deploy v2.14.0'],
    ['Seen before', '🧠 Seen before: a matching incident from 3 weeks ago, and the fix that worked'],
  ];
  for (const [heading, text] of steps) {
    await focusSlackBlock(page, heading);
    await caption(page, text);
    await shot(4);
  }

  // 4. The past incident it matched.
  await page.goto(`${WEB}/cases/1`);
  await page.waitForSelector('text=Investigation #1', { timeout: 20000 });
  await page.waitForTimeout(1500);
  await caption(page, 'The matched case: the same shift after deploy v2.9.0, three weeks ago');
  await shot(2.5);
  await page.getByRole('tab', { name: 'Resolution' }).click();
  await page.waitForTimeout(1000);
  await page.evaluate(() => {
    const status = [...document.querySelectorAll('*')].find((el) => el.childElementCount === 0 && /workflow status/i.test(el.textContent));
    if (status) window.scrollTo(0, status.getBoundingClientRect().top + window.scrollY - 110);
  });
  await page.waitForTimeout(500);
  await caption(page, 'Resolved by rolling back, and published to operational memory', 'Every resolved case makes the next alert smarter');
  await shot(4);

  // 5. Call to action.
  await page.setContent(
    card([['cmd', '$ docker compose -f docker-compose.demo.yml up']], {
      title: 'Try it yourself',
      footer: 'github.com/ramprasadgk9/ops-signals',
    }),
  );
  await shot(3.5);

  fs.writeFileSync(path.join(framesDir, 'frames.json'), JSON.stringify(frames, null, 2));
  await browser.close();
  console.log(`captured ${frames.length} frames into ${framesDir}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
