import { expect, type Page } from '@playwright/test';

/**
 * All 6 generate-and-run analyzer labs (Trend/PyOD/Prophet/Ruptures/STUMPY/Z-Score) share an
 * identical shell: a "Pattern" TextField-select drives client-side synthetic data generation, a
 * "Run Analyzer" button uploads it via the real CSV-validate pipeline (analyzer_overrides forcing
 * that lab's analyzer), and results render as a FINDING_CREATED/NO_FINDING chip plus a shared
 * PASS/FAIL chip from AnalyzerLabConfigPanel. No DB seeding needed — each lab is self-contained.
 *
 * TextField-select (as used here) wires up its accessible name correctly via MUI's built-in
 * InputLabel handling — unlike the manually-composed FormControl+InputLabel+Select pattern seen
 * elsewhere in this app (AnalyzerRecommendationPage, CaseDetailsPage), which does NOT. Confirmed
 * live: getByLabel('Pattern') works fine here.
 */
export async function runLabScenario(page: Page, path: string, patternLabel: string): Promise<void> {
  await page.goto(path);
  await page.getByLabel('Pattern').click();
  await page.getByRole('option', { name: patternLabel, exact: true }).click();
  await page.getByRole('button', { name: 'Run Analyzer' }).click();
  // Prophet/PyOD fit an actual model server-side and can run noticeably longer than the simpler
  // statistical labs (trend/ruptures/zscore/stumpy) — confirmed live, 45s covers both comfortably.
  await expect(page.getByText(/^(FINDING_CREATED|NO_FINDING)$/)).toBeVisible({ timeout: 45_000 });
}

export function expectFindingCreated(page: Page) {
  return expect(page.getByText('FINDING_CREATED', { exact: true })).toBeVisible();
}

export function expectNoFinding(page: Page) {
  return expect(page.getByText('NO_FINDING', { exact: true })).toBeVisible();
}

export function passFailChip(page: Page) {
  return page.getByText(/^(PASS|FAIL|UNKNOWN)$/);
}
