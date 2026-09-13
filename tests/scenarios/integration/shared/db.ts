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

/**
 * Inserts an ops_operational_signals row directly, bypassing analyzer execution. Behavior
 * Intelligence's fact extractor (backend/app/behavior_intelligence/fact_extractor.py) groups
 * signals by signal_type — "anomaly"/"anomaly_zscore" -> anomaly.*, "trend" -> trend.*,
 * "baseline_shift" -> baseline_shift.*, "ruptures" -> ruptures.* — so seeding a signal with a
 * specific signal_type deterministically controls which facts a dry-run/evaluate sees, without
 * depending on which analyzer the live router happens to pick for a given data shape (confirmed
 * live: the router's own analyzer_registry.yaml has no "anomaly_zscore" entry at all, so ad-hoc
 * ingestion under selection_mode=recommended_threshold can never select it — only the autonomous
 * policy path forces it. Seeding directly sidesteps that gap for testing the evaluation engine
 * itself, same "seed directly, don't wait on the full detector" pattern as seedFinding below).
 *
 * Defaults start_time/end_time to a 10-minute window ending now, not a zero-duration instant —
 * confirmed live that two zero-duration signals even a few seconds apart (as two sequential
 * `new Date()` calls naturally produce) never overlap, so BehaviorIntelligence's correlation
 * check (minimum_overlap) always fails between them even though their conditions all pass. Real
 * analyzer signals span real windows (confirmed live: ~30-40 minutes for a batch analysis run),
 * so a realistic window is what a seeded signal needs to correlate the way a real one would.
 */
export async function seedSignal(params: {
  runId: string;
  service: string;
  metricName: string;
  signalType: string;
  analyzerId?: string;
  importanceScore?: number;
  evidence?: Record<string, unknown>;
  startTime?: Date;
  endTime?: Date;
}): Promise<string> {
  const signalId = `integration-signal-${randomUUID()}`;
  const now = new Date();
  const defaultStart = new Date(now.getTime() - 10 * 60_000);
  await pool.query(
    `insert into ops_operational_signals
       (signal_id, signal_type, analyzer_id, metric_name, service, confidence, start_time, end_time,
        summary, evidence_json, importance_score, status, analysis_run_id, created_at)
     values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'new', $12, now())`,
    [
      signalId,
      params.signalType,
      params.analyzerId ?? params.signalType,
      params.metricName,
      params.service,
      params.importanceScore ?? 0.85,
      params.startTime ?? defaultStart,
      params.endTime ?? now,
      'Integration suite seeded signal.',
      JSON.stringify(params.evidence ?? {}),
      params.importanceScore ?? 0.85,
      params.runId,
    ]
  );
  return signalId;
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
  /** Defaults to now() — override to seed a finding outside the 24h window but inside 7d, etc. */
  createdAt?: Date;
}): Promise<number> {
  const findingId = params.findingId ?? makeFindingId();
  await pool.query(
    `insert into ops_operational_findings
       (id, analysis_run_id, service, metric_name, title, summary, category, health_status,
        importance_score, investigation_priority, signal_ids, comparison_json, created_at)
     values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, coalesce($13, now()))`,
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
      params.createdAt ?? null,
    ]
  );
  return findingId;
}

/** Seeds ops_behavior_findings directly — for testing the occurrence_count/last_seen_at display
 * on BehaviorIntelligencePage without waiting on a real detection to fire and re-fire. */
export async function seedBehaviorFinding(params: {
  service: string;
  definitionId?: string;
  title?: string;
  occurrenceCount?: number;
  createdAt?: Date;
  lastSeenAt?: Date;
}): Promise<number> {
  const result = await pool.query(
    `insert into ops_behavior_findings
       (behavior_id, definition_id, definition_version, title, summary, category, severity, service,
        input_metrics_json, facts_json, evidence_json, matched_conditions_json, confidence,
        correlation_json, occurrence_count, last_seen_at, created_at)
     values ($1, $2, 1, $3, $4, 'integration', 'high', $5, '{}', '{}', '[]', '[]', 0.9, '{}', $6, $7, $8)
     returning id`,
    [
      params.definitionId ?? 'integration_seeded_pattern',
      params.definitionId ?? 'integration_seeded_pattern',
      params.title ?? 'Integration suite seeded behavior finding',
      'Seeded directly for integration test setup.',
      params.service,
      params.occurrenceCount ?? 1,
      params.lastSeenAt ?? new Date(),
      params.createdAt ?? new Date(),
    ]
  );
  return result.rows[0].id;
}

export async function cleanupBehaviorFinding(id: number): Promise<void> {
  await pool.query(`delete from ops_behavior_findings where id = $1`, [id]);
}

export async function getCaseByFindingId(findingId: number): Promise<Record<string, unknown> | null> {
  const result = await pool.query(`select * from ops_operational_cases where finding_id = $1`, [findingId]);
  return result.rows[0] ?? null;
}

export async function getCaseById(caseId: number): Promise<Record<string, unknown> | null> {
  const result = await pool.query(`select * from ops_operational_cases where id = $1`, [caseId]);
  return result.rows[0] ?? null;
}

/** Mirrors the real "Create Case" action (POST /api/cases/findings/{id}/create) rather than
 * hand-inserting a case row — a case's finding_snapshot has more fields than convenient to
 * replicate by hand, and CaseDetailsPage crashes on an incomplete snapshot (confirmed live). */
export async function createCaseFromFinding(backendUrl: string, findingId: number): Promise<{ case_id: number }> {
  const response = await fetch(`${backendUrl}/api/cases/findings/${findingId}/create`, { method: 'POST' });
  if (!response.ok) {
    throw new Error(`Failed to create case from finding ${findingId}: ${response.status} ${await response.text()}`);
  }
  return response.json();
}

export async function getAnalysisRunStatus(runId: string): Promise<string | null> {
  const result = await pool.query(`select status from analysis_runs where id = $1`, [runId]);
  return result.rows[0]?.status ?? null;
}

export async function cleanupRun(params: { runId: string; findingId?: number | number[] }): Promise<void> {
  const { runId, findingId } = params;
  const findingIds = findingId == null ? [] : Array.isArray(findingId) ? findingId : [findingId];
  for (const id of findingIds) {
    await pool.query(`delete from ops_operational_cases where finding_id = $1`, [id]);
    await pool.query(`delete from ops_operational_findings where id = $1`, [id]);
  }
  await pool.query(`delete from ops_normalized_timeseries_points where analysis_run_id = $1`, [runId]);
  await pool.query(`delete from ops_operational_signals where analysis_run_id = $1`, [runId]);
  await pool.query(`delete from ops_behavior_findings where analysis_run_id = $1`, [runId]);
  await pool.query(`delete from analysis_runs where id = $1`, [runId]);
}

export async function cleanupBehaviorPatternSuggestionsForService(service: string): Promise<void> {
  await pool.query(`delete from behavior_pattern_suggestions where service = $1`, [service]);
}

export async function closeDb(): Promise<void> {
  await pool.end();
}
