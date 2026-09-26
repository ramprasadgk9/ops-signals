import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import type { SeedPoint } from './db';

// Purpose-built fixtures with documented expected routing behavior — see
// sample_data/ops_signals_test_series/README.md. Reused as-is rather than inventing new waveforms.
const FIXTURE_DIR = path.resolve(__dirname, '../../../../sample_data/ops_signals_test_series');

export type RoutingOutcome = 'recommended' | 'optional' | 'conditional' | 'not_recommended';

/** Title Case bucket labels used by ValidateDataPage's Router Decisions panel — see
 * routerBucketLabel() in frontend/src/pages/ValidateDataPage.tsx. Distinct vocabulary from the
 * lowercase recommended/conditional/not_recommended used by AnalyzerRecommendationPage's chat flow. */
export type CsvRouterBucket = 'Recommended' | 'Optional' | 'Rejected' | 'Not Recommended';

export type AnalyzerFixture = {
  file: string;
  csvPath: string;
  service: string;
  metricName: 'cpu_usage';
  /** analyzer_id -> expected recommendation for the (currently broken, test.fixme'd) chat flow —
   * see seeded-sample-routing-outcomes.spec.ts. Not re-verified since that flow doesn't work yet. */
  expectedOutcomes: Record<string, RoutingOutcome>;
  /** analyzer_id -> real router bucket, captured directly from a live CSV-validate run against
   * this exact fixture (2026-09-08). Used by csv-upload-routing-outcomes.spec.ts. Where this
   * disagrees with the README's "Expected routing behavior" table (fixture 04 notably does), it
   * asserts the REAL current behavior, not the documented one — see the discrepancy note in
   * csv-upload-routing-outcomes.spec.ts. */
  csvRouterOutcomes: Record<string, CsvRouterBucket>;
};

// analyzer_id values below match experiments/analyzer_router/analyzer_registry.yaml exactly
// (the router's ids, not the narrower set of runtime-executable ids — see docs/16-analyzer-recommendation.md
// "Router-to-pipeline mapping", e.g. "trend_regression" routes to but is distinct from executable "trend").
export const analyzerFixtures: Record<string, AnalyzerFixture> = {
  ruptures: {
    file: '01_ruptures_abrupt_regime_shift.csv',
    csvPath: path.join(FIXTURE_DIR, '01_ruptures_abrupt_regime_shift.csv'),
    service: 'test-ruptures-abrupt-regime-shift',
    metricName: 'cpu_usage',
    expectedOutcomes: { ruptures: 'recommended', trend_regression: 'not_recommended' },
    csvRouterOutcomes: { ruptures: 'Recommended', pyod_outlier: 'Not Recommended' },
  },
  trend: {
    file: '02_trend_smooth_linear_increase.csv',
    csvPath: path.join(FIXTURE_DIR, '02_trend_smooth_linear_increase.csv'),
    service: 'test-trend-smooth-linear-increase',
    metricName: 'cpu_usage',
    expectedOutcomes: { trend_regression: 'recommended', prophet: 'recommended' },
    csvRouterOutcomes: { trend_regression: 'Recommended', stumpy: 'Not Recommended', ruptures: 'Optional' },
  },
  stumpy: {
    file: '03_stumpy_repeating_motif.csv',
    csvPath: path.join(FIXTURE_DIR, '03_stumpy_repeating_motif.csv'),
    service: 'test-stumpy-repeating-motif',
    metricName: 'cpu_usage',
    expectedOutcomes: { stumpy: 'recommended' },
    csvRouterOutcomes: { stumpy: 'Recommended', pyod_outlier: 'Not Recommended' },
  },
  pyodOutlier: {
    file: '04_pyod_adtk_isolated_spikes.csv',
    csvPath: path.join(FIXTURE_DIR, '04_pyod_adtk_isolated_spikes.csv'),
    service: 'test-pyod-adtk-isolated-spikes',
    metricName: 'cpu_usage',
    expectedOutcomes: { pyod_outlier: 'recommended', ruptures: 'optional' },
    // README says PyOD/ADTK should be primary here; the live router instead recommends
    // stumpy/prophet/trend_regression/darts and rejects pyod_outlier/adtk. Asserting real
    // behavior per this suite's scope decision — see the discrepancy note in the spec file.
    csvRouterOutcomes: { stumpy: 'Recommended', pyod_outlier: 'Not Recommended', adtk: 'Not Recommended' },
  },
  mixed: {
    file: '05_kats_mixed_behavior.csv',
    csvPath: path.join(FIXTURE_DIR, '05_kats_mixed_behavior.csv'),
    service: 'test-kats-mixed-behavior',
    metricName: 'cpu_usage',
    expectedOutcomes: { kats: 'recommended', stumpy: 'not_recommended' },
    csvRouterOutcomes: { kats: 'Recommended', ruptures: 'Recommended', stumpy: 'Not Recommended' },
  },
};

function parseCsv(csvPath: string): { timestamp: string; value: number }[] {
  const text = readFileSync(csvPath, 'utf-8').trim();
  const [, ...rows] = text.split('\n');
  return rows.map((row) => {
    const [timestamp, value] = row.split(',');
    return { timestamp, value: Number(value) };
  });
}

let uploadTmpDir: string | null = null;

/**
 * The fixture CSVs use `timestamp,cpu_usage` columns, built for dev/mock_prometheus_target.py's
 * Prometheus-scrape replay — NOT for direct upload. The CSV ingestion endpoint requires
 * `timestamp,metric,value[,service,...]` (confirmed live: uploading a fixture as-is fails with
 * "CSV is missing required columns: ['metric', 'value']"). This reshapes one into an uploadable
 * temp file with the same underlying values.
 */
export function writeUploadableCsv(fixture: AnalyzerFixture): string {
  const rows = parseCsv(fixture.csvPath);
  const lines = ['timestamp,metric,value,service'];
  for (const row of rows) {
    lines.push(`${row.timestamp},${fixture.metricName},${row.value},${fixture.service}`);
  }
  uploadTmpDir ??= mkdtempSync(path.join(tmpdir(), 'ops-signals-integration-'));
  const outPath = path.join(uploadTmpDir, fixture.file);
  writeFileSync(outPath, lines.join('\n'));
  return outPath;
}

/**
 * Loads a fixture CSV and rebases its timestamps so the last sample lands at "now",
 * preserving the original spacing. Used to seed deterministic history directly into
 * Postgres for live-Prometheus scenarios, instead of waiting on real scrape accumulation.
 */
export function loadFixtureAsSeedPoints(fixture: AnalyzerFixture): SeedPoint[] {
  const rows = parseCsv(fixture.csvPath);
  const originalTimestamps = rows.map((row) => new Date(row.timestamp).getTime());
  const lastOriginal = originalTimestamps[originalTimestamps.length - 1];
  const now = Date.now();
  return rows.map((row, index) => ({
    timestamp: new Date(now - (lastOriginal - originalTimestamps[index])),
    value: row.value,
  }));
}
