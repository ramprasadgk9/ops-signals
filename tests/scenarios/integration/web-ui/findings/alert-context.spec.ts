import { test, expect } from '@playwright/test';
import { cleanupRun, makeRunId, seedFinding, seedPrometheusRun, seedSignal } from '../../shared/db';

/**
 * Findings borrow what a Prometheus alert on their metric says (docs/finding-wording.md, "What does
 * a Prometheus alert on the metric add to a finding?"). Uses the demo alert in
 * grafana/prometheus/rules/ops-signals-demo.yml:
 *
 *   - alert: DemoMixedLabLatencyHigh
 *     expr: request_latency_p95{service="mixed-lab"} > 300
 *     for: 1m
 *
 * Skipped when the connected Prometheus doesn't serve it (the alerting overlay isn't mounted).
 */
const ALERT = 'DemoMixedLabLatencyHigh';

async function seedLatencyStep(name: string, before = 180, after = 450): Promise<{ runId: string; findingId: number }> {
  const runId = makeRunId(name);
  const changedAt = new Date(Date.now() - 30 * 60_000);
  await seedPrometheusRun({ runId, service: 'mixed-lab', metricName: 'request_latency_p95', promql: 'request_latency_p95{service="mixed-lab"}' });
  const signalId = await seedSignal({
    runId,
    service: 'mixed-lab',
    metricName: 'request_latency_p95',
    signalType: 'ruptures',
    analyzerId: 'ruptures',
    evidence: { left_mean: before, right_mean: after, percent_change: ((after - before) / before) * 100, change_point_time: changedAt.toISOString() },
  });
  const findingId = await seedFinding({
    runId,
    service: 'mixed-lab',
    metricName: 'request_latency_p95',
    category: 'behavior_change',
    title: 'request_latency_p95 experienced a persistent baseline shift during the selected time window.',
    signalIds: [signalId],
  });
  return { runId, findingId };
}

test("a finding shows the alert's line and words, marked as coming from the alert", async ({ page }) => {
  const { runId, findingId } = await seedLatencyStep('alert-context');
  try {
    const finding = await (await page.request.get(`/api/findings/${findingId}`)).json();
    test.skip(finding.plain?.alert?.name !== ALERT, `the connected Prometheus has no ${ALERT} alert`);

    await page.goto(`/findings?finding=${findingId}`);
    const plain = page.getByTestId('finding-details-plain').getByTestId('finding-plain');
    await expect(plain).toContainText('Alert line', { timeout: 20_000 });
    await expect(plain).toContainText(/Above the 300 ms alert line since .+\. Alert DemoMixedLabLatencyHigh fires once it stays past the line for 1 minute\./);
    // The demo alert has only a summary, a title: Why it matters stays the template's, and the
    // summary shows in the tooltip that names the alert.
    await expect(plain).toContainText(finding.plain.why);
    await expect(plain).not.toContainText(finding.plain.alert.summary);

    await plain.getByText('Alert line', { exact: true }).hover();
    await expect(page.getByRole('tooltip')).toContainText(`From the Prometheus alert ${ALERT} ("${finding.plain.alert.summary}")`);
  } finally {
    await cleanupRun({ runId, findingId });
  }
});

test('a value already past the line before the change does not say when the alert fires', async ({ page }) => {
  const { runId, findingId } = await seedLatencyStep('alert-context-past', 400, 650);
  try {
    const finding = await (await page.request.get(`/api/findings/${findingId}`)).json();
    test.skip(finding.plain?.alert?.name !== ALERT, `the connected Prometheus has no ${ALERT} alert`);

    await page.goto(`/findings?finding=${findingId}`);
    const plain = page.getByTestId('finding-details-plain').getByTestId('finding-plain');
    await expect(plain).toContainText('Above the 300 ms alert line both before and after the change.', { timeout: 20_000 });
    await expect(plain).not.toContainText('fires once');
  } finally {
    await cleanupRun({ runId, findingId });
  }
});

test('the note under the PromQL box names the alerts that use a recording rule', async ({ page }) => {
  // Needs a local alert on service:error_rate:percent (see recording-rules.spec.ts for the rule).
  const res = await page.request.get('/api/prometheus/recording-rules');
  const rules: Array<{ name: string; alerts?: Array<{ name: string }> }> = res.ok() ? (await res.json()).rules : [];
  const rule = rules.find((item) => item.name === 'service:error_rate:percent' && item.alerts?.length);
  test.skip(!rule, 'no alert on the lab recording rule service:error_rate:percent');

  await page.goto('/validate-data');
  const hideGuide = page.getByTestId('demo-guide').getByRole('button', { name: 'Hide' });
  if (await hideGuide.isVisible().catch(() => false)) await hideGuide.click();
  await page.getByRole('tab', { name: 'Prometheus' }).click();
  await page.getByPlaceholder('Select or type metric').fill(rule!.name);
  await page.getByRole('option', { name: /^service:error_rate:percent/ }).click();

  const alert = page.getByTestId('recording-rule-note').getByTestId('recording-rule-alert').first();
  await expect(alert).toContainText(`Used by alert ${rule!.alerts![0].name}`);
});
