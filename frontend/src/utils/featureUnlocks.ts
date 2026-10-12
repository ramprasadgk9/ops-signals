import type { FeatureAvailability, SourceId } from '../types';

const OTHER_SOURCE_NAMES: Record<SourceId, string> = {
  otlp: 'OTLP',
  prometheus: 'Prometheus',
  alertmanager: 'Alertmanager',
  grafana: 'Grafana',
  events: 'deploy events',
};

export type Unlock = { id: string; label: string; on: boolean; note: string | null };

/** What connecting `source` turns on, for its Integrations tile. A metrics source (OTLP) turns on
 * the features any source runs; the others turn on the features that name them. Empty when the
 * backend sent no requirements (older backends), so the tile shows nothing new. */
export function unlocksFor(source: SourceId, features: FeatureAvailability[] | undefined): Unlock[] {
  if (!features?.length || !features.some((feature) => feature.needs)) return [];
  return features
    .filter((feature) => {
      const needs = feature.needs ?? [];
      const extras = feature.better_with ?? [];
      if (source === 'otlp') return needs.length === 0 && extras.length === 0;
      return needs.includes(source) || extras.includes(source);
    })
    .map((feature) => {
      const others = (feature.needs ?? []).filter((need) => need !== source);
      const onlyCompletes = !(feature.needs ?? []).includes(source) && source !== 'otlp';
      const parts = [
        ...(onlyCompletes ? ['more complete'] : []),
        ...(others.length ? [`with ${others.map((other) => OTHER_SOURCE_NAMES[other] ?? other).join(' and ')}`] : []),
      ];
      return { id: feature.id, label: feature.label, on: feature.state === 'on', note: parts.length ? parts.join(', ') : null };
    });
}
