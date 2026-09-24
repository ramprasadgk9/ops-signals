// Captures the documentation screenshots (docs/screenshots/images/web + the Slack-style alert) from
// a running demo with showcase data. Run through scripts/record_screenshots.sh.
//
//   node demo/screenshots/capture.cjs <output-root> [only-name ...]
//
// Uses the Playwright + Chromium that the frontend's integration tests already install.

const path = require('path');
const fs = require('fs');
const os = require('os');
const { chromium } = require(path.join(__dirname, '..', '..', 'frontend', 'node_modules', 'playwright'));

const WEB = process.env.DEMO_WEB_URL || 'http://localhost:8080';
const SLACK = process.env.DEMO_SLACK_SINK_URL || 'http://localhost:8090';
const VIEWPORT = { width: 1920, height: 960 };
const ROOT = path.join(__dirname, '..', '..');

// A small Prometheus-format CSV (timestamp,metric,value) from a bundled sample series.
function sampleCsv() {
  const source = fs.readFileSync(path.join(ROOT, 'sample_data', 'ops_signals_test_series', '01_ruptures_abrupt_regime_shift.csv'), 'utf8');
  const rows = source.trim().split('\n').slice(1).map((line) => {
    const [timestamp, value] = line.split(',');
    return `${timestamp},cpu_usage,${value}`;
  });
  const file = path.join(os.tmpdir(), 'payments-api-cpu.csv');
  fs.writeFileSync(file, ['timestamp,metric,value', ...rows].join('\n') + '\n');
  return file;
}

async function settle(page, ms = 1500) {
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(ms);
}

async function scrollToText(page, text, offset = 120) {
  await page.evaluate(([t, o]) => {
    const el = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6,p,span,div')].find(
      (node) => node.childElementCount === 0 && node.textContent.trim() === t,
    );
    if (el) window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - o);
  }, [text, offset]);
  await page.waitForTimeout(500);
}

const SHOTS = {
  async '01-overview'(page) {
    await page.goto(`${WEB}/`);
    await settle(page, 2500);
  },

  async '02-new-analysis-csv'(page) {
    await page.goto(`${WEB}/validate-data`);
    await settle(page);
    await page.getByLabel('Service').fill('payments-api');
    await page.getByLabel('Metric').fill('cpu_usage');
    await page.locator('input[type=file]').setInputFiles(sampleCsv());
    await page.getByRole('button', { name: 'Validate Data' }).click();
    await page.getByText('No router decisions returned yet.').waitFor({ state: 'detached', timeout: 60000 });
    await settle(page, 3000);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(500);
  },

  async '03-new-analysis-prometheus'(page) {
    await page.goto(`${WEB}/validate-data`);
    await settle(page);
    await page.getByRole('tab', { name: 'Prometheus' }).click();
    await settle(page);
    // The demo's checkout-api latency series. Switch to Advanced first: changing the mode regenerates
    // the PromQL from Service/Metric, which would overwrite a query typed before it.
    await page.getByRole('combobox').filter({ hasText: 'Simple' }).click();
    await page.getByRole('option', { name: 'Advanced PromQL' }).click();
    await page.waitForTimeout(500);
    await page.getByRole('textbox', { name: 'PromQL' }).fill('request_latency_p95{service="checkout-api"}');
    await page.waitForTimeout(500);
    await page.getByRole('button', { name: 'Preview Data' }).click();
    await page.getByText('Series Returned').waitFor();
    await settle(page, 3000);
  },

  async '04-findings'(page) {
    await page.goto(`${WEB}/findings`);
    await settle(page, 2500);
  },

  async '05-case-details'(page) {
    const cases = await (await fetch(`${WEB}/api/cases`)).json();
    const resolved = cases.find((c) => c.outcome_status === 'resolved' && c.finding_snapshot?.service === 'payments-api') || cases[0];
    await page.goto(`${WEB}/cases/${resolved.id}`);
    await settle(page, 2500);
  },

  async '06-behavior-intelligence'(page) {
    await page.goto(`${WEB}/behavior-intelligence`);
    await settle(page, 2500);
  },

  async '07-operational-memory'(page) {
    await page.goto(`${WEB}/operational-memory`);
    await settle(page, 2500);
  },

  async '08-assistant'(page) {
    await page.goto(`${WEB}/assistant`);
    await settle(page);
    const input = page.getByRole('textbox').last();
    await input.fill('Show similar cases for request_latency_p95 on checkout-api');
    await page.getByRole('button', { name: 'Send' }).click();
    await page.waitForTimeout(8000);
    await settle(page, 1500);
  },

  async '09-analyzer-recommendation'(page) {
    await page.goto(`${WEB}/analyzer-recommendation`);
    await settle(page);
    await page.getByLabel('Metric Name').fill('cpu_usage');
    await page.getByLabel('Metric Description').fill('CPU utilization of the payments API pods.');
    await page.getByRole('button', { name: 'CPU Template' }).click();
    const sampleSelect = page.getByText('Select Existing Sample', { exact: true }).locator('xpath=following-sibling::*[1]').getByRole('combobox');
    await sampleSelect.click();
    await page.getByRole('option', { name: /payments-api \/ cpu_usage/ }).first().click();
    await page.getByRole('button', { name: 'Evaluate with Sample' }).click();
    await page.getByText('Recommendation Results').waitFor({ timeout: 30000 });
    await settle(page, 1500);
    await scrollToText(page, 'Recommendation Results', 110);
  },
};

// Grafana plugin screens. Needs a Grafana at GRAFANA_URL with the plugin built against this
// backend (see scripts/record_screenshots.sh) and a Prometheus datasource with the mock lab series.
const GRAFANA = process.env.GRAFANA_URL || 'http://localhost:3000';
const PLUGIN = `${GRAFANA}/a/breezypoppy3596-ops-signals-app`;
const GRAFANA_VIEWPORT = { width: 1920, height: 1040 };
const PLUGIN_SERVICE = 'test-ruptures-abrupt-regime-shift';
const PLUGIN_METRIC = 'ops_signals_test_cpu_usage';

async function pluginSelect(page) {
  await page.goto(PLUGIN);
  await page.getByRole('button', { name: 'Run Analysis' }).waitFor();
  await page.waitForTimeout(1500);
  await page.getByPlaceholder(/Value for label/).fill(PLUGIN_SERVICE);
  await page.getByPlaceholder('Metric name').fill(PLUGIN_METRIC);
  // Matched by visible text: this button's accessible name comes out as the whole preset group.
  await page.locator('button', { hasText: /^Last 30m$/ }).click();
  await page.waitForTimeout(500);
}

async function pluginRun(page) {
  await pluginSelect(page);
  await page.getByRole('button', { name: 'Run Analysis' }).click();
  await page.getByRole('button', { name: 'View Evidence' }).first().waitFor({ timeout: 60000 });
  await page.waitForTimeout(2500);
}

async function scrollIntoTop(page, locator, offset = 70) {
  await locator.first().evaluate((el, o) => {
    const scroller = document.scrollingElement;
    let node = el.parentElement;
    while (node && node !== document.body) {
      if (node.scrollHeight > node.clientHeight + 10 && /(auto|scroll)/.test(getComputedStyle(node).overflowY)) break;
      node = node.parentElement;
    }
    const target = node && node !== document.body ? node : scroller;
    target.scrollTop += el.getBoundingClientRect().top - o - (target === scroller ? 0 : target.getBoundingClientRect().top);
  }, offset);
  await page.waitForTimeout(700);
}

const GRAFANA_SHOTS = {
  async '00-home-page'(page) {
    await page.goto(PLUGIN);
    await page.getByRole('button', { name: 'Run Analysis' }).waitFor();
    await page.waitForTimeout(2000);
  },

  async '01-prometheus-selection'(page) {
    await pluginSelect(page);
  },

  async '02-metrics-analysis'(page) {
    await pluginRun(page);
    await scrollIntoTop(page, page.getByText('Samples', { exact: true }), 120);
  },

  async '03-case-flow'(page) {
    await pluginRun(page);
    await page.getByRole('button', { name: 'View Evidence' }).first().click();
    await page.waitForTimeout(2000);
  },

  async '04-recent-cases'(page) {
    await pluginRun(page);
    await page.getByRole('button', { name: 'Create Case' }).first().click();
    await page.getByText('No case created yet').waitFor({ state: 'detached', timeout: 30000 }).catch(() => {});
    await page.waitForTimeout(2500);
    await scrollIntoTop(page, page.getByText('Recent investigations', { exact: true }), 420);
  },

  async '05-ask-ops-signals'(page) {
    await pluginRun(page);
    await page.getByRole('button', { name: 'Why was this detected?' }).first().click();
    await page.waitForTimeout(8000);
    const panel = page.getByText('Ask Ops Signals', { exact: true }).locator('xpath=ancestor::*[self::section or self::div][.//button[normalize-space()="Ask"]][1]');
    // Bring the answer into view, then clip to the panel below Grafana's 48px top bar.
    await scrollIntoTop(page, page.getByText('Assistant answer', { exact: true }), 560);
    const box = await panel.first().boundingBox();
    const top = Math.max(box.y, 56);
    return { clip: { x: box.x, y: top, width: box.width, height: Math.min(box.y + box.height, GRAFANA_VIEWPORT.height) - top } };
  },

  async '06-autonomous-analysis'(page) {
    await page.goto(PLUGIN);
    await page.getByRole('button', { name: /Autonomous Analysis/ }).click();
    await page.waitForTimeout(3500);
  },
};

async function grafanaLogin(browser) {
  const context = await browser.newContext({ viewport: GRAFANA_VIEWPORT, deviceScaleFactor: 1, colorScheme: 'dark' });
  const page = await context.newPage();
  await page.goto(`${GRAFANA}/login`);
  await page.fill('input[name=user]', process.env.GRAFANA_USER || 'admin');
  await page.fill('input[name=password]', process.env.GRAFANA_PASSWORD || 'admin');
  await page.click('button[type=submit]');
  await page.waitForTimeout(2000);
  const skip = page.getByRole('button', { name: /Skip/ });
  if (await skip.isVisible().catch(() => false)) await skip.click();
  return page;
}

const SLACK_SHOT = 'enriched-alert-demo';

async function captureSlack(page, outRoot) {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(SLACK);
  await page.waitForSelector('.msg', { timeout: 15000 });
  await page.waitForTimeout(800);
  const file = path.join(outRoot, 'slack', `${SLACK_SHOT}.png`);
  await page.locator('.msg').first().screenshot({ path: file });
  console.log(`captured ${path.relative(ROOT, file)}`);
}

async function main() {
  const [outRoot, ...only] = process.argv.slice(2);
  if (!outRoot) throw new Error('usage: capture.cjs <output-root> [only-name ...]');
  fs.mkdirSync(path.join(outRoot, 'web'), { recursive: true });
  fs.mkdirSync(path.join(outRoot, 'slack'), { recursive: true });
  fs.mkdirSync(path.join(outRoot, 'grafana-plugin'), { recursive: true });

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: VIEWPORT, deviceScaleFactor: 1, colorScheme: 'light' });
  const failures = [];
  for (const [name, drive] of Object.entries(SHOTS)) {
    if (only.length && !only.includes(name)) continue;
    try {
      await page.setViewportSize(VIEWPORT);
      await drive(page);
      const file = path.join(outRoot, 'web', `${name}.png`);
      await page.screenshot({ path: file });
      console.log(`captured ${path.relative(ROOT, file)}`);
    } catch (error) {
      failures.push(name);
      console.error(`FAILED ${name}: ${error.message.split('\n')[0]}`);
    }
  }
  if (!only.length || only.includes(SLACK_SHOT)) {
    await captureSlack(page, outRoot).catch((error) => {
      failures.push(SLACK_SHOT);
      console.error(`FAILED ${SLACK_SHOT}: ${error.message.split('\n')[0]}`);
    });
  }
  const wantGrafana = only.length ? only.some((name) => name in GRAFANA_SHOTS) : process.env.SKIP_GRAFANA !== '1';
  if (wantGrafana) {
    const grafanaPage = await grafanaLogin(browser);
    for (const [name, drive] of Object.entries(GRAFANA_SHOTS)) {
      if (only.length && !only.includes(name)) continue;
      try {
        const element = await drive(grafanaPage);
        const file = path.join(outRoot, 'grafana-plugin', `${name}.png`);
        if (element?.clip) await grafanaPage.screenshot({ path: file, clip: element.clip });
        else await grafanaPage.screenshot({ path: file });
        console.log(`captured ${path.relative(ROOT, file)}`);
      } catch (error) {
        failures.push(name);
        console.error(`FAILED ${name}: ${error.message.split('\n')[0]}`);
      }
    }
  }
  await browser.close();
  if (failures.length) process.exit(1);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
