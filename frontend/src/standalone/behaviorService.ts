import type { BehaviorDefinition, BehaviorFinding } from '../types';
import { patternParts, patternStatus } from '../utils/combinedPatterns';

export type BehaviorSummary = {
  /** Seen by a run in the last 24 hours. */
  activeBehaviors: number;
  /** Distinct metrics the detected behaviors combine. */
  metricsCombined: number;
  affectedServices: number;
  confidenceAverage: number | null;
};

export type BehaviorRow = {
  id: number;
  title: string;
  pattern: string;
  severity: string;
  confidencePercent: number;
  impactedServices: string;
  detectedAt: string;
  lastSeenAt: string;
  occurrenceCount: number;
  status: 'active' | 'quiet';
  evidence: string[];
  summary: string;
  caseId: number | null;
};

export type BehaviorRuleRow = {
  id: string;
  title: string;
  description: string;
  version: number;
  status: 'active' | 'disabled';
  sourceFile: string;
};

export function buildBehaviorSummary(findings: BehaviorFinding[], now = Date.now()): BehaviorSummary {
  return {
    activeBehaviors: findings.filter((item) => patternStatus(item, now) === 'active').length,
    metricsCombined: new Set(findings.flatMap((item) => patternParts(item).map((part) => part.metric))).size,
    affectedServices: new Set(findings.map((item) => item.service).filter(Boolean)).size,
    confidenceAverage: findings.length ? Math.round((findings.reduce((total, item) => total + item.confidence, 0) / findings.length) * 100) : null,
  };
}

export function toBehaviorRows(findings: BehaviorFinding[], now = Date.now()): BehaviorRow[] {
  return findings.map((finding) => ({
    id: finding.id,
    title: finding.title,
    pattern: finding.category || 'unknown',
    severity: finding.severity,
    confidencePercent: Math.round(finding.confidence * 100),
    impactedServices: finding.service ?? 'unavailable',
    detectedAt: finding.created_at,
    lastSeenAt: finding.last_seen_at,
    occurrenceCount: finding.occurrence_count,
    status: patternStatus(finding, now),
    evidence: finding.evidence_json ?? [],
    summary: finding.summary,
    caseId: finding.case_id ?? null,
  }));
}

export function toBehaviorRuleRows(definitions: BehaviorDefinition[]): BehaviorRuleRow[] {
  return definitions.map((definition) => ({
    id: definition.id,
    title: definition.title,
    description: definition.description,
    version: definition.version,
    status: definition.enabled ? 'active' : 'disabled',
    sourceFile: definition.source_file ?? 'unknown',
  }));
}
