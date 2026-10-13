// Records the "OTLP only" walkthrough the README shows: an empty install, the endpoint to point a
// Collector at, then the same kind of install after a real Collector has been sending for a while.
// Run through scripts/record_otlp_walkthrough.sh, which starts nothing itself: it needs two
// sandboxes (scripts/otlp_sandbox.sh), one left empty and one with live Collector data.
//
//   EMPTY_URL=http://localhost:5185 LIVE_URL=http://localhost:5184 node demo/otlp_walkthrough/capture.cjs <work-dir>
//
// Writes <work-dir>/walkthrough.webm and <work-dir>/frames/{NN.png,frames.json}. Read-only: it
// clicks nothing that changes either sandbox.

const path = require('path');
const fs = require('fs');
const { chromium } = require(path.join(__dirname, '..', '..', 'frontend', 'node_modules', 'playwright'));
const { OVERLAY_SCRIPT, card, caption, focus, bringIntoView, pointAt, clickOn } = require('../walkthrough_kit.cjs');

const EMPTY = process.env.EMPTY_URL || 'http://localhost:5185';
const LIVE = process.env.LIVE_URL || 'http://localhost:5184';
const VIEWPORT = { width: 1280, height: 800 };

async function main() {
  const [workDir] = process.argv.slice(2);
  if (!workDir) throw new Error('usage: capture.cjs <work-dir>');
  const framesDir = path.join(workDir, 'frames');
  const videoDir = path.join(workDir, 'video');
  fs.mkdirSync(framesDir, { recursive: true });

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
    await page.setContent(
      card({
        kicker: 'Ops Signals · OTLP only',
        title: 'Already on OpenTelemetry? Send metrics straight in',
        steps: [
          ['Step 1', 'Point your Collector', 'Its otlphttp exporter, at one URL. No Prometheus needed.'],
          ['Step 2', 'Data arrives', 'Each series is analyzed every 10 minutes, with its history.'],
          ['Step 3', 'Findings', 'Counted once per problem, with when it started and if it is over.'],
        ],
      }),
    );
    await shot(4);
    await hold(4000);

    // Before: an empty install.
    await page.goto(`${EMPTY}/`);
    await page.getByText('Ops Signals hasn’t received any data yet').waitFor({ timeout: 30000 });
    await page.mouse.move(640, 400);
    await hold(800);
    await caption(page, '<b>Before</b> · A new install with nothing connected', 'No Prometheus, no Alertmanager. Only an OTLP endpoint waiting for data.');
    await focus(page, page.getByText('Ops Signals hasn’t received any data yet'));
    await hold(2500);
    await shot(3.5);

    const otlpTile = page.getByText('Send metrics via OTLP');
    await bringIntoView(page, otlpTile, 120);
    await focus(page, otlpTile.locator('xpath=../../..'));
    await caption(page, '<b>Step 1</b> · Point your Collector’s otlphttp exporter here', 'Copy the endpoint. Gauges and counters are analyzed; counters as per-second rates.');
    await pointAt(page, otlpTile);
    await hold(3000);
    await shot(4);
    await focus(page, null);

    // After: a real Collector has been sending host and container metrics.
    await page.goto(`${LIVE}/`);
    const strip = page.getByRole('status', { name: 'Data sources' });
    await strip.waitFor({ timeout: 30000 });
    await page.getByRole('link', { name: /Need Attention/ }).waitFor({ timeout: 30000 });
    await hold(800);
    await caption(page, '<b>Step 2</b> · A real Collector has been sending for over an hour', 'Host and Docker container metrics, about 300 series. OTLP shows green.');
    await focus(page, strip);
    await pointAt(page, strip);
    await hold(3000);
    await shot(4);

    const kpi = page.getByRole('link', { name: /Need Attention/ });
    await focus(page, kpi);
    await caption(page, '<b>Step 3</b> · The problems worth a look, each counted once', 'Context findings stay one click away. A problem seen again by a later analysis is not counted again.');
    await pointAt(page, kpi);
    await hold(3000);
    await shot(3.5);
    await focus(page, null);

    // Findings, each with when it happened.
    await page.goto(`${LIVE}/findings?window=6h`);
    const timing = page.getByTestId('finding-timing').first();
    await timing.waitFor({ timeout: 30000 });
    await bringIntoView(page, timing, 220);
    await caption(page, '<b>Findings</b> · When it started, and whether it is still happening', 'A problem that ended says so: "09:00–09:45 · over".');
    await focus(page, timing);
    await pointAt(page, timing);
    await hold(3500);
    await shot(4.5);
    await focus(page, null);

    // What works with OTLP alone, and what needs another source.
    await page.goto(`${LIVE}/integrations`);
    const moreGroup = page.getByText('More with Prometheus / Grafana');
    await moreGroup.waitFor({ timeout: 30000 });
    await focus(page, moreGroup.locator('xpath=..'));
    await caption(page, '<b>Needs another source</b> · These move to their own menu group', 'Each one explains what to connect when you open it.');
    await pointAt(page, moreGroup);
    await hold(3000);
    await shot(3.5);
    await focus(page, null);
    const works = page.getByRole('button', { name: 'What works with my data?' });
    await works.waitFor({ timeout: 30000 });
    await bringIntoView(page, works, 160);
    await caption(page, '<b>What works with OTLP alone?</b> The app tells you');
    await clickOn(page, works);
    const panel = page.getByRole('table', { name: 'Feature availability' });
    await panel.waitFor({ timeout: 10000 });
    await hold(900);
    await caption(page, '<b>On:</b> findings, cases, memory, Slack, assistant · <b>Needs Prometheus:</b> autonomous analysis, pod drill-down', 'Alert enrichment also needs Alertmanager. Latency percentiles wait for OTLP histograms.');
    await focus(page, panel);
    await hold(4500);
    await shot(5);
    await focus(page, null);
    await page.keyboard.press('Escape');
    await hold(700);

    await page.setContent(
      card({
        kicker: 'Try it on your machine',
        title: 'An empty OTLP-only copy, next to your own',
        steps: [
          ['Start', './scripts/otlp_sandbox.sh up', 'Own database. Touches nothing else.'],
          ['Send data', '… collector', 'A real OTel Collector with this machine’s metrics.'],
          ['Clean up', '… down', 'Removes it all.'],
        ],
        footer: 'Expect the first findings after about 10 minutes, and steadier ones after 40.',
      }),
    );
    await hold(4500);
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
