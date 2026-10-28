import { test, expect } from '@playwright/test';
import { env } from '../../shared/env';
import { makeRunId, seedFinding, createCaseFromFinding, cleanupRun } from '../../shared/db';

/**
 * The Shift handoff card on the Overview (backend/app/services/shift_handoff.py). The counts come
 * from a shared dev database, so the API check compares against a baseline; the card's watch list
 * and copy are checked with the handoff stubbed.
 */

type Handoff = { new_findings: number; cases_opened: number; cases_still_open: number; watch: Array<{ case_id?: number | null }> };

async function fetchHandoff(request: import('@playwright/test').APIRequestContext): Promise<Handoff> {
  const response = await request.get(`${env.webUiBackendUrl}/api/overview/handoff?hours=12`);
  expect(response.status()).toBe(200);
  return response.json();
}

test('a new finding and case show up in the handoff counts', async ({ page }) => {
  const runId = makeRunId('shift-handoff');
  const baseline = await fetchHandoff(page.request);
  const findingId = await seedFinding({ runId, service: `shift-handoff-${runId}`, metricName: 'error_rate', title: `Shift handoff ${runId}`, healthStatus: 'critical' });
  const { case_id: caseId } = await createCaseFromFinding(env.webUiBackendUrl, findingId);
  try {
    const after = await fetchHandoff(page.request);
    // Scheduled runs can add findings meanwhile; cases only come from people (and this spec).
    expect(after.new_findings).toBeGreaterThanOrEqual(baseline.new_findings + 1);
    expect(after.cases_opened).toBe(baseline.cases_opened + 1);
    expect(after.cases_still_open).toBe(baseline.cases_still_open + 1);

    await page.goto('/');
    const card = page.getByTestId('shift-handoff');
    await expect(card.getByText('Shift handoff')).toBeVisible({ timeout: 20_000 });
    await expect(card.getByTestId('shift-handoff-counts')).toContainText(/\d+ new findings? · \d+ cases? opened · \d+ resolved · \d+ still open/);
    expect(caseId).toBeGreaterThan(0);
  } finally {
    await cleanupRun({ runId, findingId });
  }
});

test('the card names what to watch first and copies the note for Slack', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.route('**/api/overview/handoff?hours=*', (route) =>
    route.fulfill({
      json: {
        generated_at: '2026-10-27T12:00:00Z',
        hours: 12,
        since: '2026-10-27T00:00:00Z',
        new_findings: 4,
        cases_opened: 2,
        cases_resolved: 1,
        cases_still_open: 2,
        watch: [{ kind: 'case', title: 'Payments errors up', service: 'payments', metric_name: 'error_rate', case_id: 987654, finding_id: 1, reason: 'open 8 hours, started after deploy v2.3, critical' }],
        summary: 'Last 12 hours: 4 new findings, 2 cases opened, 1 resolved. 2 cases still open. Watch first: case #987654 (payments error_rate), open 8 hours, started after deploy v2.3, critical.',
      },
    })
  );
  await page.goto('/');
  const card = page.getByTestId('shift-handoff');
  await expect(card.getByTestId('shift-handoff-watch')).toContainText('Case #987654 · payments / error_rate', { timeout: 20_000 });
  await expect(card.getByRole('link', { name: 'Open case' })).toHaveAttribute('href', '/cases/987654');

  await card.getByRole('button', { name: 'Copy for Slack' }).click();
  await expect(card.getByRole('status')).toContainText('Copied');
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied).toContain('Watch first: case #987654');
  expect(copied).toContain('/cases/987654');
});
