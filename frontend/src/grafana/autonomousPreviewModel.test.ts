import { describe, expect, it } from 'vitest';

import { buildAutonomousPreviewRequest, filterPreviewRows, previewRowExplanation, splitCsvList } from './autonomousPreviewModel';
import type { AutonomousPlanItem } from './contracts';

const baseForm = {
  backend: 'grafana-stack',
  environment: 'production',
  allServices: true,
  selectedServices: ['checkout'],
  allNamespaces: true,
  selectedNamespaces: ['commerce'],
  serviceLabel: 'service',
  namespaceLabel: 'namespace',
  environmentLabel: 'env',
  selectedCategories: ['performance' as const],
  executionInterval: '10m',
  analysisWindow: '24h',
  maxMetricsPerRun: 500,
  maxParallelJobs: 20,
  customExplicitMetrics: '',
  customIncludePatterns: '',
  customExcludePatterns: '.*_info$,.*_created$',
};

function item(overrides: Partial<AutonomousPlanItem> = {}): AutonomousPlanItem {
  return {
    service: 'checkout',
    namespace: 'commerce',
    metric_name: 'http_request_duration_seconds',
    category: 'performance',
    concept: 'latency',
    concepts: ['latency'],
    metric_type: 'gauge',
    selector: '{service="checkout"}',
    transformation: 'raw',
    aggregation: 'avg_by_service',
    group_by: ['service'],
    promql: 'avg by (service) (http_request_duration_seconds{service="checkout"})',
    confidence: 0.94,
    selection_reason: 'exact_metric_mapping',
    matched_rule: 'http_request_duration_seconds',
    aggregation_strategy: 'p95_by_service',
    estimated_series_count: 1,
    planned: true,
    exclusion_reason: null,
    analysis_window: '24h',
    ...overrides,
  };
}

describe('autonomous preview model', () => {
  it('constructs all-services preview requests', () => {
    const request = buildAutonomousPreviewRequest(baseForm);
    expect(request.scope.all_services).toBe(true);
    expect(request.scope.services).toEqual([]);
    expect(request.monitoring_categories).toEqual(['performance']);
    expect(request.monitoring_selection?.categories).toEqual(['performance']);
  });

  it('constructs selected service and namespace filters', () => {
    const request = buildAutonomousPreviewRequest({ ...baseForm, allServices: false, allNamespaces: false });
    expect(request.scope.services).toEqual(['checkout']);
    expect(request.scope.namespaces).toEqual(['commerce']);
  });

  it('defaults to all clusters and sends selected clusters when narrowed', () => {
    expect(buildAutonomousPreviewRequest(baseForm).scope).toMatchObject({ all_clusters: true, clusters: [] });
    expect(buildAutonomousPreviewRequest({ ...baseForm, allClusters: false, selectedClusters: ['us'] }).scope).toMatchObject({
      all_clusters: false,
      clusters: ['us'],
    });
  });

  it('splits custom CSV values', () => {
    expect(splitCsvList('cpu.*, memory.*,')).toEqual(['cpu.*', 'memory.*']);
  });

  it('filters selected and excluded preview rows', () => {
    const rows = [
      item(),
      item({ metric_name: 'build_info', planned: false, category: null, concept: null, concepts: [], exclusion_reason: 'excluded_metadata_metric' }),
    ];
    expect(filterPreviewRows(rows, 'planned', 'all')).toHaveLength(1);
    expect(filterPreviewRows(rows, 'excluded', 'all')[0].metric_name).toBe('build_info');
    expect(filterPreviewRows(rows, 'all', 'performance')).toHaveLength(1);
    expect(filterPreviewRows(rows, 'all', 'all', 'latency')).toHaveLength(1);
  });

  it('explains selected and excluded rows', () => {
    expect(previewRowExplanation(item())).toContain('Selected because exact_metric_mapping');
    expect(previewRowExplanation(item({ planned: false, exclusion_reason: 'excluded_metadata_metric' }))).toContain('Excluded because excluded_metadata_metric');
  });
});
