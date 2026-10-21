import { test, expect } from '@playwright/test';
import { makeRunId, seedNormalizedPoints, seedSignal, cleanupRun } from '../../shared/db';

/**
 * Covers testing a pattern against real signals before saving, through "See it on my data" and
 * one run's details. Seeds a real ops_operational_signals row per metric (signal_type: 'anomaly',
 * which fact_extractor.py maps to <alias>.anomaly.present) rather than depending on which analyzer
 * the live router happens to pick for synthetic data (see shared/db.ts seedSignal doc comment).
 */
test.describe('Behavior Lab — a run up close', () => {
  test('a run where both metrics spiked shows each condition passed, and full confidence', async ({ page }) => {
    const runId = makeRunId('behavior-lab-run-details-match');
    const service = `behavior-lab-run-details-${Date.now()}`;
    const now = new Date();

    await seedNormalizedPoints({ runId, service, metricName: 'request_latency_p95', points: [{ timestamp: now, value: 900 }] });
    await seedNormalizedPoints({ runId, service, metricName: 'error_rate', points: [{ timestamp: now, value: 0.2 }] });
    await seedSignal({ runId, service, metricName: 'request_latency_p95', signalType: 'anomaly', importanceScore: 0.9 });
    await seedSignal({ runId, service, metricName: 'error_rate', signalType: 'anomaly', importanceScore: 0.85 });

    try {
      await page.goto('/behavior-intelligence/lab');
      await page.getByLabel('Id', { exact: true }).fill('run_details_smoke_match');
      await page.getByLabel('Title', { exact: true }).fill('Run details smoke — match');
      await page.getByLabel('Output title', { exact: true }).fill('Latency and errors both spiked');

      await page.locator('button:has-text("Add Input")').click();
      await page.getByLabel('Alias', { exact: true }).first().fill('latency');
      await page.getByLabel('Metric name', { exact: true }).first().fill('request_latency_p95');
      await page.locator('button:has-text("Add Input")').click();
      await page.getByLabel('Alias', { exact: true }).nth(1).fill('errors');
      await page.getByLabel('Metric name', { exact: true }).nth(1).fill('error_rate');

      // One condition per metric, in plain words: each "has an unusual spike".
      for (const index of [0, 1]) {
        await page.locator('button:has-text("Add all condition")').click();
        await page.getByRole('combobox', { name: 'What happens' }).nth(index).click();
        await page.getByRole('option', { name: 'has an unusual spike' }).click();
      }

      await page.getByRole('combobox', { name: 'Service' }).fill(service);
      await page.getByRole('button', { name: 'See it on my data' }).click();
      await expect(page.getByText(`Would have fired in 1 of 1 runs of ${service}`, { exact: false })).toBeVisible({ timeout: 15_000 });

      await page.getByRole('button', { name: /^Details for run/ }).click();
      await expect(page.getByText('✓ latency has an unusual spike')).toBeVisible();
      await expect(page.getByText('✓ errors has an unusual spike')).toBeVisible();
      await expect(page.getByText('Confidence: 100%')).toBeVisible();
    } finally {
      await cleanupRun({ runId });
    }
  });

  test('a run without the spike does not match, and the details say which condition failed', async ({ page }) => {
    const runId = makeRunId('behavior-lab-run-details-nomatch');
    const service = `behavior-lab-run-details-nomatch-${Date.now()}`;
    const now = new Date();

    await seedNormalizedPoints({ runId, service, metricName: 'cpu_usage', points: [{ timestamp: now, value: 40 }] });
    // Seeded as a "trend" signal, not "anomaly" — cpu.anomaly.present reads false.
    await seedSignal({ runId, service, metricName: 'cpu_usage', signalType: 'trend' });

    try {
      await page.goto('/behavior-intelligence/lab');
      await page.getByLabel('Id', { exact: true }).fill('run_details_smoke_nomatch');
      await page.getByLabel('Title', { exact: true }).fill('Run details smoke — no match');
      await page.getByLabel('Output title', { exact: true }).fill('CPU spike pattern');

      await page.locator('button:has-text("Add Input")').click();
      await page.getByLabel('Alias', { exact: true }).first().fill('cpu');
      await page.getByLabel('Metric name', { exact: true }).first().fill('cpu_usage');

      await page.locator('button:has-text("Add all condition")').click();
      await page.getByRole('combobox', { name: 'What happens' }).click();
      await page.getByRole('option', { name: 'has an unusual spike' }).click();

      await page.getByRole('combobox', { name: 'Service' }).fill(service);
      await page.getByRole('button', { name: 'See it on my data' }).click();
      await expect(page.getByText(`Never matched in 1 runs of ${service}`, { exact: false })).toBeVisible({ timeout: 15_000 });

      await page.getByRole('button', { name: /^Details for run/ }).click();
      await expect(page.getByText('✗ cpu has an unusual spike')).toBeVisible();
    } finally {
      await cleanupRun({ runId });
    }
  });
});
