import { test, expect } from '@playwright/test';
import { cleanupMetricUsageSnapshot, seedMetricUsageSnapshot } from '../../shared/db';

/**
 * Unwatched metrics on Metric Usage offer Add to Grafana (a query and the Grafana steps) and Drop
 * (Prometheus scrape config built by the backend, grouped by scrape job), and recording rules
 * nobody reads say how to remove them (README.md#metric-usage).
 */
test('unused metrics can be added to Grafana or dropped with ready-made scrape config', async ({ page }) => {
  const id = `it-unused-actions-${Date.now()}`;
  const day = 24 * 60 * 60_000;
  await seedMetricUsageSnapshot({
    id,
    items: [
      { metric: 'it_orders_cache_evictions_total', series: 8240, jobs: { default: { orders: 8240 } }, metricType: 'counter', firstSeen: new Date(Date.now() - 30 * day) },
      { metric: 'it_checkout_size_bytes_bucket', series: 5410, jobs: { default: { checkout: 5410 } }, metricType: 'histogram', analyzed: true },
      { metric: 'it_inventory_sync_lag_seconds', series: 40, jobs: { default: { inventory: 40 } }, metricType: 'gauge', firstSeen: new Date(Date.now() - 2 * day) },
      { metric: 'it_instance:cpu:avg', series: 240, recordingRule: true },
    ],
    unreadRules: [{ name: 'it_instance:cpu:avg', groups: ['node'], connections: ['default'], reads: ['node_cpu_seconds_total'], feeds: [], series: 240, analyzed: false }],
  });

  try {
    await page.goto('/metric-usage');
    await page.getByRole('button', { name: 'See these metrics →' }).click({ timeout: 20_000 });
    const section = page.getByTestId('metric-usage-section-unwatched');
    await expect(section.getByText('it_orders_cache_evictions_total')).toBeVisible();
    await expect(section.getByText(/Drop is offered in 5 days/)).toBeVisible();
    await expect(section.getByRole('checkbox', { name: 'Select it_inventory_sync_lag_seconds' })).toBeDisabled();
    await expect(section.getByText('Made by a recording rule: see Recording rules nobody reads.')).toBeVisible();

    await section.getByRole('checkbox', { name: 'Select it_orders_cache_evictions_total' }).check();
    await section.getByRole('checkbox', { name: 'Select it_checkout_size_bytes_bucket' }).check();
    await expect(section.getByTestId('drop-selection')).toHaveText('2 selected · 13,650 series');
    await section.getByRole('button', { name: 'Drop 2 metrics' }).click();

    const drop = page.getByRole('dialog');
    const yaml = drop.getByTestId('drop-config-yaml');
    await expect(yaml).toContainText('- job_name: checkout');
    await expect(yaml).toContainText("regex: 'it_orders_cache_evictions_total'");
    await expect(yaml).toContainText('action: drop');
    await expect(drop.getByText('13,650 series stop being stored')).toBeVisible();
    await expect(drop.getByTestId('metric-usage-checked-note')).toContainText('3 dashboards and 2 alert rules in Grafana');
    await expect(drop.getByText(/it_checkout_size_bytes_bucket: Ops Signals analyzes this metric/)).toBeVisible();
    await drop.getByRole('button', { name: 'Close' }).click();

    const row = section.getByTestId('metric-usage-row').filter({ hasText: 'it_orders_cache_evictions_total' });
    await row.getByRole('button', { name: 'Add to Grafana' }).click();
    const add = page.getByRole('dialog');
    await expect(add.getByTestId('watch-query')).toHaveText('sum by (job) (rate(it_orders_cache_evictions_total[5m]))');
    await add.getByRole('button', { name: 'Close' }).click();

    const rules = page.getByTestId('metric-usage-section-unread-rules');
    await rules.getByRole('button', { name: /Recording rules nobody reads/ }).click();
    await rules.getByRole('button', { name: 'How to remove' }).click();
    await expect(page.getByRole('dialog')).toContainText('delete the rule record: it_instance:cpu:avg from group node');
  } finally {
    await cleanupMetricUsageSnapshot(id);
  }
});
