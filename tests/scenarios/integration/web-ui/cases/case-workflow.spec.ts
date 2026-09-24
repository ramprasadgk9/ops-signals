import { test, expect } from '@playwright/test';
import { env } from '../../shared/env';
import { makeRunId, seedFinding, createCaseFromFinding, getCaseById, cleanupRun } from '../../shared/db';

/**
 * Drives all three case workflow tabs (Investigation / Root Cause / Resolution) against one real
 * seeded case, verifying each PATCH actually persisted in Postgres — not just that the UI shows a
 * success state, since none of these mutations show a visible confirmation (they just invalidate
 * the query cache and silently refetch; see CaseDetailsPage.tsx's onSuccess handlers).
 *
 * MUI Select's `label` prop doesn't wire up an accessible name here either (same issue as
 * AnalyzerRecommendationPage's "Select Existing Sample" — confirmed live), so these use
 * getByRole('combobox') scoped to one tab panel at a time, where exactly one combobox is visible.
 * The scoping matters: the app header's global search is an Autocomplete, also a combobox, so an
 * unscoped page.getByRole('combobox') matches two elements. getByRole('tabpanel') skips the
 * hidden panels, leaving only the selected one.
 */
test('investigation, root cause, and resolution updates all persist to Postgres', async ({ page }) => {
  const runId = makeRunId('case-workflow');
  const findingId = await seedFinding({
    runId,
    service: 'checkout-api',
    metricName: 'memory_usage',
    title: `Integration suite case-workflow finding ${runId}`,
  });
  const { case_id: caseId } = await createCaseFromFinding(env.webUiBackendUrl, findingId);

  try {
    await page.goto(`/cases/${caseId}`);

    // --- Investigation ---
    await page.getByRole('tab', { name: 'Investigation' }).click();
    await page.getByRole('tabpanel').getByRole('combobox').click();
    await page.getByRole('option', { name: 'In Progress' }).click();
    const noteText = `Checked dashboards, ruled out deploy correlation. ${runId}`;
    await page.getByLabel('Investigation note').fill(noteText);
    await page.getByRole('button', { name: 'Save Investigation' }).click();
    // setInvestigationNote('') runs only in the mutation's onSuccess, so waiting for the field to
    // clear is a real signal the PATCH resolved, not just that the button was clicked.
    await expect(page.getByLabel('Investigation note')).toHaveValue('', { timeout: 15_000 });

    let persisted = await getCaseById(caseId);
    expect(persisted?.investigation_status).toBe('in_progress');
    // Not asserting the note itself landed in investigation_notes — confirmed live it doesn't
    // (see the dedicated fixme'd test below for why). investigation_status persisting correctly
    // is still verified above.

    // --- Root Cause ---
    await page.getByRole('tab', { name: 'Root Cause' }).click();
    await page.getByRole('tabpanel').getByRole('combobox').click();
    await page.getByRole('option', { name: 'Identified' }).click();
    const rcaSummary = `Checkout deploy increased request volume, saturating CPU. ${runId}`;
    await page.getByLabel('Root cause summary').fill(rcaSummary);
    await page.getByLabel('Confidence (0-1)').fill('0.85');
    await page.getByLabel('Verified by investigation evidence').check();
    await page.getByRole('button', { name: 'Save Root Cause' }).click();
    // No visible success signal on this tab (see file header) — poll Postgres directly instead.
    await expect
      .poll(async () => (await getCaseById(caseId))?.root_cause_status, { timeout: 15_000 })
      .toBe('identified');

    persisted = await getCaseById(caseId);
    expect(persisted?.root_cause_summary).toBe(rcaSummary);
    expect(Number(persisted?.root_cause_confidence)).toBeCloseTo(0.85, 2);
    expect(persisted?.root_cause_verified).toBe(true);

    // --- Resolution ---
    // "Resolved" is deliberately not exercised here — confirmed live it 400s server-side (see the
    // dedicated fixme'd test below). "Escalated" isn't a final state, so it isn't subject to that
    // validation, and still exercises the same Select-and-Save flow.
    await page.getByRole('tab', { name: 'Resolution' }).click();
    await page.getByRole('tabpanel').getByRole('combobox').click();
    await page.getByRole('option', { name: 'Escalated' }).click();
    const outcomeSummary = `Needs platform team involvement. ${runId}`;
    const correctiveAction = `Escalate to platform team. ${runId}`;
    await page.getByLabel('Outcome summary').fill(outcomeSummary);
    await page.getByLabel('Corrective action').fill(correctiveAction);
    await page.getByRole('button', { name: 'Save Resolution' }).click();
    await expect
      .poll(async () => (await getCaseById(caseId))?.outcome_status, { timeout: 15_000 })
      .toBe('escalated');

    persisted = await getCaseById(caseId);
    expect(persisted?.outcome_summary).toBe(outcomeSummary);
    expect(persisted?.corrective_action).toBe(correctiveAction);
  } finally {
    await cleanupRun({ runId, findingId });
  }
});

test('marking a case Resolved from the Resolution tab actually resolves it', async ({ page }) => {
  test.fixme(
    true,
    'PATCH /api/cases/{id}/resolution 400s with "learning_outcome_status is required when resolving or ' +
      'closing a case" whenever outcome_status is a final state (resolved/closed) — confirmed live via ' +
      'direct curl. The Resolution tab UI has no field for learning_outcome_status at all (not in ' +
      'CaseDetailsPage.tsx, not in the updateResolution() payload type in api/queries.ts), and ' +
      'updateResolutionMutation has no onError handler, so this fails completely silently: the Select ' +
      'shows "Resolved" and nothing on screen indicates the save failed, but outcome_status stays whatever ' +
      'it was before. This blocks the one workflow the Resolution tab exists for. Needs either a ' +
      'learning_outcome_status field added to the UI, or the backend requirement relaxed/defaulted.'
  );

  const runId = makeRunId('case-resolve-bug');
  const findingId = await seedFinding({
    runId,
    service: 'checkout-api',
    metricName: 'memory_usage',
    title: `Integration suite case-resolve-bug finding ${runId}`,
  });
  const { case_id: caseId } = await createCaseFromFinding(env.webUiBackendUrl, findingId);

  try {
    await page.goto(`/cases/${caseId}`);
    await page.getByRole('tab', { name: 'Resolution' }).click();
    await page.getByRole('tabpanel').getByRole('combobox').click();
    await page.getByRole('option', { name: 'Resolved' }).click();
    await page.getByRole('button', { name: 'Save Resolution' }).click();

    await expect
      .poll(async () => (await getCaseById(caseId))?.outcome_status, { timeout: 15_000 })
      .toBe('resolved');
  } finally {
    await cleanupRun({ runId, findingId });
  }
});

test('investigation notes are appended to investigation_notes', async ({ page }) => {
  test.fixme(
    true,
    'PATCH /api/cases/{id}/investigation calls case.investigation_notes.append({...}) — an in-place ' +
      'mutation of the JSON column value — then db.commit(). SQLAlchemy only tracks reassignment of a ' +
      'JSON-column attribute, not in-place mutation of the object it points to, so the append is silently ' +
      'lost: db.refresh(case) even returns the correctly-appended list within THIS request/session, making ' +
      'the API response look right, but a fresh query afterward shows investigation_notes unchanged. ' +
      'Confirmed live via direct curl + a follow-up Postgres read. investigation_status (plain scalar ' +
      'reassignment on the same endpoint) persists correctly — this is specific to the notes list. ' +
      'Fix: reassign (case.investigation_notes = [...case.investigation_notes, {...}]) or use ' +
      "sqlalchemy.orm.attributes.flag_modified(case, 'investigation_notes')."
  );

  const runId = makeRunId('case-notes-bug');
  const findingId = await seedFinding({
    runId,
    service: 'checkout-api',
    metricName: 'memory_usage',
    title: `Integration suite case-notes-bug finding ${runId}`,
  });
  const { case_id: caseId } = await createCaseFromFinding(env.webUiBackendUrl, findingId);

  try {
    await page.goto(`/cases/${caseId}`);
    await page.getByRole('tab', { name: 'Investigation' }).click();
    const noteText = `Note that should persist. ${runId}`;
    await page.getByLabel('Investigation note').fill(noteText);
    await page.getByRole('button', { name: 'Save Investigation' }).click();
    await expect(page.getByLabel('Investigation note')).toHaveValue('', { timeout: 15_000 });

    const persisted = await getCaseById(caseId);
    const notes = persisted?.investigation_notes as Array<{ note?: string }> | undefined;
    expect(notes?.some((entry) => entry.note === noteText)).toBe(true);
  } finally {
    await cleanupRun({ runId, findingId });
  }
});
