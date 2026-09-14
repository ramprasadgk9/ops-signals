import type { BehaviorDefinition, BehaviorFinding } from '../types';

export type BehaviorSummary = {
  activeBehaviors: number;
  totalSignals: number;
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
  status: 'active';
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

export function buildBehaviorSummary(findings: BehaviorFinding[]): BehaviorSummary {
  return {
    activeBehaviors: findings.length,
    totalSignals: findings.reduce((total, item) => total + (item.evidence_json?.length ?? 0), 0),
    affectedServices: new Set(findings.map((item) => item.service).filter(Boolean)).size,
    confidenceAverage: findings.length ? Math.round((findings.reduce((total, item) => total + item.confidence, 0) / findings.length) * 100) : null,
  };
}

export function toBehaviorRows(findings: BehaviorFinding[]): BehaviorRow[] {
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
    status: 'active',
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
