import { test, expect } from '@playwright/test';
import { cleanupChangeEvents, cleanupRun, makeRunId, seedChangeEvent, seedFinding, seedSignal } from '../../shared/db';

/**
 * A deploy Ops Signals found in Prometheus (docs/deploy-discovery.md) shows under the finding's
 * What changed with a "Found automatically" tag; one sent by CI doesn't get the tag.
 */
test('a deploy found in Prometheus is tagged "Found automatically" under What changed', async ({ page }) => {
  const runId = makeRunId('found-deploy-tag');
  const service = `found-deploy-${runId.slice(-8)}`;
  const changeAt = new Date(Date.now() - 10 * 60_000);
  const signalId = await seedSignal({
    runId,
    service,
    metricName: 'http_latency',
    signalType: 'ruptures',
    analyzerId: 'ruptures',
    evidence: { change_point_time: changeAt.toISOString() },
    startTime: changeAt,
    endTime: new Date(),
  });
  const findingId = await seedFinding({ runId, service, metricName: 'http_latency', category: 'behavior_change', signalIds: [signalId] });
  await seedChangeEvent({
    service,
    timestamp: new Date(changeAt.getTime() - 4 * 60_000),
    version: '1.0.1',
    source: 'ops-signals:build_info',
    description: 'Found automatically: version changed from 1.0.0 to 1.0.1 (build_info metric).',
  });
  await seedChangeEvent({ service, timestamp: new Date(changeAt.getTime() - 20 * 60_000), version: 'v0.9', source: 'ci' });

  try {
    await page.goto(`/findings?finding=${findingId}`);
    const whatChanged = page.getByTestId('finding-what-changed');
    await expect(whatChanged).toContainText('Started 4 min after deploy 1.0.1', { timeout: 20_000 });
    await expect(whatChanged).toContainText('Started 20 min after deploy v0.9');

    const tags = whatChanged.getByText('Found automatically', { exact: true });
    await expect(tags).toHaveCount(1);
    await tags.hover();
    await expect(page.getByRole('tooltip')).toContainText('version changed from 1.0.0 to 1.0.1');
  } finally {
    await cleanupChangeEvents(service);
    await cleanupRun({ runId, findingId });
  }
});
