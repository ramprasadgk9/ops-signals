import { test, expect, type Page } from '@playwright/test';
import { cleanupInvestigations, cleanupRun, makeRunId, seedFinding, seedPrometheusRun, seedSignal } from '../../shared/db';
import { env } from '../../shared/env';

/**
 * Investigate on a finding (docs/investigate.md). The investigation endpoints are stubbed in the
 * browser, so the specs don't depend on an AI provider or on what a model answers; the backend's
 * own start-info answer and the real service notes are checked against the stack.
 */

async function seedInvestigable(name: string): Promise<{ runId: string; findingId: number; service: string }> {
  const runId = makeRunId(name);
  const service = `investigate-${runId.slice(-8)}`;
  const metricName = 'http_request_duration_seconds';
  await seedPrometheusRun({ runId, service, metricName, promql: `histogram_quantile(0.95, sum by (le) (rate(${metricName}_bucket{service="${service}"}[5m])))` });
  const signalId = await seedSignal({ runId, service, metricName, signalType: 'baseline_shift', analyzerId: 'ruptures' });
  const findingId = await seedFinding({ runId, service, metricName, category: 'behavior_change', healthStatus: 'critical', title: 'Latency jumped', signalIds: [signalId] });
  return { runId, findingId, service };
}

function investigation(findingId: number, service: string, overrides: Record<string, unknown> = {}) {
  return {
    id: 901, finding_id: findingId, service, status: 'done', ending: 'found', ending_detail: null,
    summary: `${service} started waiting for its database at 22:28. Look there next.`, question: null,
    round: 1, checks_used: 2, check_budget: 15, case_id: null, model: 'test-model', started_by: 'priya',
    context_note: null, skipped_sources: [], created_at: null, updated_at: null,
    checks: [{ ref: 'c1', round: 1, tool: 'query_range', purpose: 'Waiting for the database?', query: 'db_client_wait_seconds', ok: true, result: '1 series: rose at 22:28.', at: null }],
    steps: [
      { id: 1, round: 1, position: 1, kind: 'checked', status: 'worth_a_look', title: 'Waiting for the database', why: 'It rose two minutes before latency.', result: 'Wait went from 2 ms to 1.5 s at 22:28.', evidence: ['c1'], unverified: false, mark: null, note: null, marked_by: null },
      { id: 2, round: 1, position: 2, kind: 'your_step', status: 'todo', title: 'Check the node pool move', why: "The database isn't connected.", result: 'When did the move finish?', evidence: [], unverified: false, mark: null, note: null, marked_by: null },
    ],
    ...overrides,
  };
}

async function stubInvestigation(page: Page, findingId: number, service: string): Promise<{ started: () => unknown }> {
  let startBody: unknown = null;
  let polls = 0;
  await page.route('**/api/investigations/start-info?*', async (route) => {
    const response = await route.fetch();
    const real = await response.json();
    await route.fulfill({ json: { ...real, ai_on: true } });
  });
  await page.route('**/api/investigations', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    startBody = route.request().postDataJSON();
    await route.fulfill({ json: investigation(findingId, service, { status: 'running', ending: null, summary: null, steps: [] }) });
  });
  await page.route('**/api/investigations/901', async (route) => {
    polls += 1;
    await route.fulfill({ json: polls < 2 ? investigation(findingId, service, { status: 'running', ending: null, summary: null, steps: [] }) : investigation(findingId, service) });
  });
  await page.route('**/api/investigations/901/steps/1', (route) =>
    route.fulfill({ json: investigation(findingId, service, { steps: [{ ...investigation(findingId, service).steps[0], mark: 'found', marked_by: 'priya' }, investigation(findingId, service).steps[1]] }) })
  );
  return { started: () => startBody };
}

test('the backend says a Prometheus finding can be investigated', async ({ page }) => {
  const { runId, findingId, service } = await seedInvestigable('investigate-api');
  try {
    const info = await (await page.request.get(`${env.webUiBackendUrl}/api/investigations/start-info?finding_id=${findingId}`)).json();
    expect(info.eligible).toBe(true);
    expect(info.has_query).toBe(true);
    expect(info.service).toBe(service);
  } finally {
    await cleanupRun({ runId, findingId });
  }
});

test('first investigation of a service: describe it, start, and mark what was found', async ({ page }) => {
  const { runId, findingId, service } = await seedInvestigable('investigate-flow');
  const stub = await stubInvestigation(page, findingId, service);
  try {
    await page.goto(`/findings?finding=${findingId}`);
    await page.getByTestId('drawer-investigate-button').click({ timeout: 20_000 });

    const dialog = page.getByTestId('investigate-dialog');
    await expect(dialog.getByText('Help it start in the right place')).toBeVisible();
    await dialog.getByLabel('Add a dependency').fill('checkout-db');
    await dialog.getByLabel('Kind').click();
    await page.getByRole('option', { name: 'database' }).click();
    await dialog.getByRole('button', { name: 'Add', exact: true }).first().click();
    await dialog.getByLabel('Anything about today?').fill('We moved the database to a new node pool this evening.');
    await dialog.getByLabel(/Past cases/).uncheck();
    await dialog.getByTestId('start-investigation').click();

    await expect(dialog.getByTestId('investigation-ending')).toContainText('Found where to look', { timeout: 20_000 });
    expect(stub.started()).toEqual({ finding_id: findingId, note: 'We moved the database to a new node pool this evening.', save_note: false, skipped_sources: ['cases'] });
    const notes = await (await page.request.get(`${env.webUiBackendUrl}/api/service-notes/${service}`)).json();
    expect(notes.depends_on).toEqual([{ name: 'checkout-db', kind: 'database' }]);

    const steps = dialog.getByTestId('investigation-step');
    await expect(steps).toHaveCount(2);
    await steps.first().getByRole('button', { name: 'Show query' }).click();
    await expect(steps.first()).toContainText('db_client_wait_seconds');
    await steps.first().getByRole('button', { name: 'Found something' }).click();
    await expect(steps.first()).toContainText('You found something');
  } finally {
    await cleanupInvestigations(service);
    await cleanupRun({ runId, findingId });
  }
});
