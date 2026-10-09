import type { AutonomousPlanItem, AutonomousPreviewRequest, MonitoringCategory } from './contracts';

export type AutonomousPreviewForm = {
  backend: string;
  environment: string;
  allServices: boolean;
  selectedServices: string[];
  allNamespaces: boolean;
  selectedNamespaces: string[];
  allClusters?: boolean;
  selectedClusters?: string[];
  serviceLabel: string;
  namespaceLabel: string;
  environmentLabel: string;
  selectedCategories: MonitoringCategory[];
  executionInterval: string;
  analysisWindow: string;
  maxMetricsPerRun: number | string;
  maxParallelJobs: number | string;
  customExplicitMetrics: string;
  customIncludePatterns: string;
  customExcludePatterns: string;
  connectionId?: string;
};

export function splitCsvList(value: string) {
  return value.split(',').map((item) => item.trim()).filter(Boolean);
}

function parsePositiveInteger(value: number | string, fallback: number) {
  const parsed = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(parsed) || parsed < 1) return fallback;
  return Math.floor(parsed);
}

export function buildAutonomousPreviewRequest(form: AutonomousPreviewForm): AutonomousPreviewRequest {
  const maxMetricsPerRun = parsePositiveInteger(form.maxMetricsPerRun, 500);
  const maxParallelJobs = parsePositiveInteger(form.maxParallelJobs, 20);

  return {
    datasource: 'prometheus',
    backend: form.backend,
    ...(form.connectionId ? { connection_id: form.connectionId } : {}),
    scope: {
      environment: form.environment || null,
      services: form.allServices ? [] : form.selectedServices,
      namespaces: form.allNamespaces ? [] : form.selectedNamespaces,
      all_services: form.allServices,
      all_namespaces: form.allNamespaces,
      service_label: form.serviceLabel,
      namespace_label: form.namespaceLabel,
      environment_label: form.environmentLabel,
      clusters: form.allClusters === false ? form.selectedClusters ?? [] : [],
      all_clusters: form.allClusters ?? true,
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
      max_metrics_per_run: maxMetricsPerRun,
      max_parallel_jobs: maxParallelJobs,
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

/** The connection and clusters a plan request covers: the picked connection, else the backend's
 * default; the picked clusters still offered by that connection, and all clusters when none are. */
export function autonomousSourceFor(input: {
  connections: Array<{ id: string; is_default?: boolean }>;
  pickedConnectionId: string | null;
  allClusters: boolean;
  pickedClusters: string[];
  clusterOptions: string[];
}): { connectionId?: string; allClusters: boolean; selectedClusters: string[] } {
  // `default` is the backend's alias for its default connection: name that connection by its own id.
  const picked = input.pickedConnectionId === 'default' ? null : input.pickedConnectionId;
  const connectionId = picked ?? input.connections.find((connection) => connection.is_default)?.id ?? input.pickedConnectionId ?? undefined;
  const selectedClusters = input.pickedClusters.filter((cluster) => input.clusterOptions.includes(cluster));
  return {
    ...(connectionId ? { connectionId } : {}),
    allClusters: input.allClusters || selectedClusters.length === 0,
    selectedClusters,
  };
}
