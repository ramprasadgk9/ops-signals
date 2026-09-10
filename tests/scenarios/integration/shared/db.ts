import { randomUUID } from 'node:crypto';
import { Pool } from 'pg';
import { env } from './env';

function toNodePgConnectionString(url: string): string {
  // SQLAlchemy-style "postgresql+psycopg://" isn't understood by node-postgres.
  return url.replace('postgresql+psycopg://', 'postgresql://');
}

const pool = new Pool({ connectionString: toNodePgConnectionString(env.databaseUrl) });

export function makeRunId(scenario: string): string {
  return `integration-${scenario}-${randomUUID()}`;
}

export function makeFindingId(): number {
  // Mirrors the old Python integration test's approach: a large random int, not a DB-assigned serial,
  // so a finding can be seeded directly without racing the app's own id sequence.
  return Math.floor(Math.random() * 2_000_000_000) + 1;
}

export type SeedPoint = { timestamp: Date; value: number };

export async function seedNormalizedPoints(params: {
  runId: string;
  service: string;
  metricName: string;
  points: SeedPoint[];
}): Promise<void> {
  const { runId, service, metricName, points } = params;
  for (const point of points) {
    await pool.query(
      `insert into ops_normalized_timeseries_points
         (metric_name, timestamp, value, service, analysis_run_id, created_at)
       values ($1, $2, $3, $4, $5, now())`,
      [metricName, point.timestamp, point.value, service, runId]
    );
  }
}

export async function seedFinding(params: {
  runId: string;
  service: string;
  metricName: string;
  findingId?: number;
  title?: string;
  summary?: string;
  category?: string;
  healthStatus?: string;
}): Promise<number> {
  const findingId = params.findingId ?? makeFindingId();
  await pool.query(
    `insert into ops_operational_findings
       (id, analysis_run_id, service, metric_name, title, summary, category, health_status,
        importance_score, investigation_priority, signal_ids, comparison_json, created_at)
     values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, now())`,
    [
      findingId,
      params.runId,
      params.service,
      params.metricName,
      params.title ?? 'Integration suite seeded finding',
      params.summary ?? 'Seeded directly for integration test setup.',
      params.category ?? 'trend',
      params.healthStatus ?? 'warning',
      0.8,
      2,
      JSON.stringify(['integration-seed-signal']),
      JSON.stringify({ scenario: 'integration' }),
    ]
  );
  return findingId;
}

export async function getCaseByFindingId(findingId: number): Promise<Record<string, unknown> | null> {
  const result = await pool.query(`select * from ops_operational_cases where finding_id = $1`, [findingId]);
  return result.rows[0] ?? null;
}

export async function getAnalysisRunStatus(runId: string): Promise<string | null> {
  const result = await pool.query(`select status from analysis_runs where id = $1`, [runId]);
  return result.rows[0]?.status ?? null;
}

export async function cleanupRun(params: { runId: string; findingId?: number }): Promise<void> {
  const { runId, findingId } = params;
  if (findingId != null) {
    await pool.query(`delete from ops_operational_cases where finding_id = $1`, [findingId]);
    await pool.query(`delete from ops_operational_findings where id = $1`, [findingId]);
  }
  await pool.query(`delete from ops_normalized_timeseries_points where analysis_run_id = $1`, [runId]);
  await pool.query(`delete from analysis_runs where id = $1`, [runId]);
}

export async function closeDb(): Promise<void> {
  await pool.end();
}
