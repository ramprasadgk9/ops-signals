import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import type { FeatureAvailability, SourceId } from '../types';

export const SOURCE_LABELS: Record<SourceId, string> = {
  otlp: 'OTLP',
  prometheus: 'a Prometheus-compatible source',
  alertmanager: 'Alertmanager',
  grafana: 'Grafana',
  events: 'deploy events',
};

/** "Grafana and a Prometheus-compatible source" */
export function sourceList(sources: SourceId[]): string {
  const labels = sources.map((source) => SOURCE_LABELS[source] ?? source);
  if (labels.length <= 1) return labels.join('');
  return `${labels.slice(0, -1).join(', ')} and ${labels[labels.length - 1]}`;
}

/** What the connected sources turn on, from GET /api/ingestion/status. Until that answers (or when
 * it fails) every feature reads as available, so the UI looks exactly as it did without this. */
export function useFeatureAvailability() {
  const query = useQuery({ queryKey: ['ingestion-status'], queryFn: () => api.ingestionStatus(), retry: false, refetchInterval: 60_000 });
  const status = query.data && !Array.isArray(query.data) ? query.data : undefined;
  const features = status?.features;
  return useMemo(() => {
    const byId = new Map<string, FeatureAvailability>((Array.isArray(features) ? features : []).map((feature) => [feature.id, feature]));
    return {
      status,
      feature: (id: string) => byId.get(id),
      isOff: (id: string) => byId.get(id)?.state === 'off',
    };
  }, [status, features]);
}
