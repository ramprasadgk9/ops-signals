import type { AutonomousPlanItem, AutonomousPreviewRequest, MonitoringCategory } from './contracts';

export type AutonomousPreviewForm = {
  backend: string;
  environment: string;
  allServices: boolean;
  selectedServices: string[];
  allNamespaces: boolean;
  selectedNamespaces: string[];
  serviceLabel: string;
  namespaceLabel: string;
  environmentLabel: string;
  selectedCategories: MonitoringCategory[];
  executionInterval: string;
  analysisWindow: string;
  maxMetricsPerRun: number;
  maxParallelJobs: number;
  customExplicitMetrics: string;
  customIncludePatterns: string;
  customExcludePatterns: string;
};

export function splitCsvList(value: string) {
  return value.split(',').map((item) => item.trim()).filter(Boolean);
}

export function buildAutonomousPreviewRequest(form: AutonomousPreviewForm): AutonomousPreviewRequest {
  return {
    datasource: 'prometheus',
    backend: form.backend,
    scope: {
      environment: form.environment || null,
      services: form.allServices ? [] : form.selectedServices,
      namespaces: form.allNamespaces ? [] : form.selectedNamespaces,
      all_services: form.allServices,
      all_namespaces: form.allNamespaces,
      service_label: form.serviceLabel,
      namespace_label: form.namespaceLabel,
      environment_label: form.environmentLabel,
    },
    monitoring_selection: {
      categories: form.selectedCategories,
      custom_constraints: {
        explicit_metrics: splitCsvList(form.customExplicitMetrics),
        include_patterns: splitCsvList(form.customIncludePatterns),
        exclude_patterns: splitCsvList(form.customExcludePatterns),
        required_labels: {},
        aggregation: null,
        group_by: [],
      },
    },
    monitoring_categories: form.selectedCategories,
    execution: {
      interval: form.executionInterval,
      analysis_window: form.analysisWindow,
      max_metrics_per_run: form.maxMetricsPerRun,
      max_parallel_jobs: form.maxParallelJobs,
    },
    custom_constraints: {
      explicit_metrics: splitCsvList(form.customExplicitMetrics),
      include_patterns: splitCsvList(form.customIncludePatterns),
      exclude_patterns: splitCsvList(form.customExcludePatterns),
      required_labels: {},
    },
  };
}

export function filterPreviewRows(items: AutonomousPlanItem[], statusFilter: 'all' | 'planned' | 'excluded', categoryFilter: string, conceptFilter = 'all') {
  return items.filter((item) => {
    if (statusFilter === 'planned' && !item.planned) return false;
    if (statusFilter === 'excluded' && item.planned) return false;
    if (categoryFilter !== 'all' && item.category !== categoryFilter) return false;
    if (conceptFilter !== 'all' && item.concept !== conceptFilter) return false;
    return true;
  });
}

export function previewRowExplanation(item: AutonomousPlanItem) {
  if (item.explanation) return item.explanation;
  if (item.planned) {
    return `Selected because ${item.selection_reason ?? 'it matched the selected category'}.`;
  }
  return `Excluded because ${item.exclusion_reason ?? 'it did not match the selected categories'}.`;
}
