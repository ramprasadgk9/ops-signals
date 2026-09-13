import { test, expect } from '@playwright/test';
import { makeRunId, seedNormalizedPoints, seedSignal, cleanupRun } from '../../shared/db';

/**
 * Covers "test against real historical data before saving" — the core self-service authoring
 * improvement. Seeds a real ops_operational_signals row per metric (signal_type: 'anomaly', which
 * fact_extractor.py maps to <alias>.anomaly.present/count/max_score) rather than depending on
 * which analyzer the live router happens to pick for synthetic data (confirmed live: the router's
 * analyzer_registry.yaml has no "anomaly_zscore" entry at all, so ad-hoc ingestion can never
 * select it — see shared/db.ts seedSignal doc comment). Also seeds ops_normalized_timeseries_points
 * for the same run/service/metric so the sample shows up in the "Select Existing Sample" dropdown,
 * which is powered by that table, not by ops_operational_signals.
 */
test.describe('Behavior Lab — dry run against real signals', () => {
  test('dry run matches a two-input pattern against seeded anomaly signals for the same run', async ({ page }) => {
    const runId = makeRunId('behavior-lab-dry-run-match');
    const service = `behavior-lab-dry-run-${Date.now()}`;
    const now = new Date();

    await seedNormalizedPoints({ runId, service, metricName: 'request_latency_p95', points: [{ timestamp: now, value: 900 }] });
    await seedNormalizedPoints({ runId, service, metricName: 'error_rate', points: [{ timestamp: now, value: 0.2 }] });
    await seedSignal({ runId, service, metricName: 'request_latency_p95', signalType: 'anomaly', importanceScore: 0.9 });
    await seedSignal({ runId, service, metricName: 'error_rate', signalType: 'anomaly', importanceScore: 0.85 });

    try {
      await page.goto('/behavior-intelligence/lab');
      await page.getByLabel('Id', { exact: true }).fill('dry_run_smoke_match');
      await page.getByLabel('Title', { exact: true }).fill('Dry run smoke — match');
      await page.getByLabel('Output title', { exact: true }).fill('Latency and errors both anomalous');

      await page.locator('button:has-text("Add Input")').click();
      await page.getByLabel('Alias', { exact: true }).first().fill('latency');
      await page.getByLabel('Metric name', { exact: true }).first().fill('request_latency_p95');
      await page.locator('button:has-text("Add Input")').click();
      await page.getByLabel('Alias', { exact: true }).nth(1).fill('errors');
      await page.getByLabel('Metric name', { exact: true }).nth(1).fill('error_rate');

      await page.locator('button:has-text("Add all condition")').click();
      await page.getByPlaceholder('cpu.anomaly.present').first().fill('latency.anomaly.present');
      await page.locator('button:has-text("Add all condition")').click();
      await page.getByPlaceholder('cpu.anomaly.present').nth(1).fill('errors.anomaly.present');

      // The MUI Select's `label` prop doesn't wire up aria-labelledby here (same known gap as
      // AnalyzerRecommendationPage's sample dropdown — see seeded-sample-routing-outcomes.spec.ts),
      // so getByLabel finds nothing — anchor off the InputLabel's visible text instead.
      const sampleSelect = page
        .getByText('Select Existing Sample', { exact: true })
        .locator('xpath=following-sibling::*[1]')
        .getByRole('combobox');
      await sampleSelect.click();
      await page.getByRole('option', { name: new RegExp(`${service} / request_latency_p95`) }).click();

      await page.locator('button:has-text("Test Pattern")').click();

      await expect(page.getByText('MATCHED', { exact: true })).toBeVisible({ timeout: 15_000 });
      await expect(page.getByText('Confidence: 100%')).toBeVisible();
      await expect(page.getByText(/latency\.anomaly\.present equals true/)).toBeVisible();
      await expect(page.getByText(/errors\.anomaly\.present equals true/)).toBeVisible();
    } finally {
      await cleanupRun({ runId });
    }
  });

  test('dry run reports NOT_MATCHED when the seeded signal has no anomaly', async ({ page }) => {
    const runId = makeRunId('behavior-lab-dry-run-nomatch');
    const service = `behavior-lab-dry-run-nomatch-${Date.now()}`;
    const now = new Date();

    await seedNormalizedPoints({ runId, service, metricName: 'cpu_usage', points: [{ timestamp: now, value: 40 }] });
    // Seeded as a "trend" signal, not "anomaly" — latency.anomaly.present should read false.
    await seedSignal({ runId, service, metricName: 'cpu_usage', signalType: 'trend' });

    try {
      await page.goto('/behavior-intelligence/lab');
      await page.getByLabel('Id', { exact: true }).fill('dry_run_smoke_nomatch');
      await page.getByLabel('Title', { exact: true }).fill('Dry run smoke — no match');
      await page.getByLabel('Output title', { exact: true }).fill('CPU anomaly pattern');

      await page.locator('button:has-text("Add Input")').click();
      await page.getByLabel('Alias', { exact: true }).first().fill('cpu');
      await page.getByLabel('Metric name', { exact: true }).first().fill('cpu_usage');

      await page.locator('button:has-text("Add all condition")').click();
      await page.getByPlaceholder('cpu.anomaly.present').fill('cpu.anomaly.present');

      // The MUI Select's `label` prop doesn't wire up aria-labelledby here (same known gap as
      // AnalyzerRecommendationPage's sample dropdown — see seeded-sample-routing-outcomes.spec.ts),
      // so getByLabel finds nothing — anchor off the InputLabel's visible text instead.
      const sampleSelect = page
        .getByText('Select Existing Sample', { exact: true })
        .locator('xpath=following-sibling::*[1]')
        .getByRole('combobox');
      await sampleSelect.click();
      await page.getByRole('option', { name: new RegExp(`${service} / cpu_usage`) }).click();

      await page.locator('button:has-text("Test Pattern")').click();

      await expect(page.getByText('NOT_MATCHED', { exact: true })).toBeVisible({ timeout: 15_000 });
    } finally {
      await cleanupRun({ runId });
    }
  });
});
