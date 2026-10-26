/** The Service filter on Findings, Cases and the plugin overview. Shared by both builds, so it stays
 * free of UI imports. */

/** URL value (`?service=(none)`) for findings and cases that carry no service. */
export const NO_SERVICE_KEY = '(none)';

// How "no service" is stored: autonomous runs write "unknown", OTLP without service.name writes
// "unknown-service", case rows show "n/a".
const NO_SERVICE_VALUES = new Set(['', 'unknown', 'unknown-service', 'n/a']);

export type ServiceOption = { key: string; label: string; count: number };

export function serviceKey(service?: string | null): string {
  const value = (service ?? '').trim();
  return NO_SERVICE_VALUES.has(value) ? NO_SERVICE_KEY : value;
}

export function serviceFilterLabel(key: string): string {
  return key === NO_SERVICE_KEY ? 'No service label' : key;
}

/** One option per service with its count, busiest first and "No service label" last. A selected
 * service with nothing in the list is kept (count 0) so the choice stays visible and can be cleared. */
export function serviceOptions(items: Array<{ service?: string | null }>, selected?: string | null): ServiceOption[] {
  const counts = new Map<string, number>();
  for (const item of items) {
    const key = serviceKey(item.service);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  if (selected && !counts.has(selected)) counts.set(selected, 0);
  return [...counts.entries()]
    .map(([key, count]) => ({ key, label: serviceFilterLabel(key), count }))
    .sort((a, b) => Number(a.key === NO_SERVICE_KEY) - Number(b.key === NO_SERVICE_KEY) || b.count - a.count || a.label.localeCompare(b.label));
}

/** The filter appears when there is a choice: two or more services, or one already picked. */
export function showServiceFilter(options: ServiceOption[], selected?: string | null): boolean {
  return options.length > 1 || Boolean(selected);
}

export function inService<T extends { service?: string | null }>(items: T[], selected: string | null | undefined): T[] {
  return selected ? items.filter((item) => serviceKey(item.service) === selected) : items;
}

/** Cases carry their service in the finding snapshot they were opened from. */
export function casesInService<T extends { finding_snapshot?: Record<string, unknown> | null }>(cases: T[], selected: string | null | undefined): T[] {
  return selected ? cases.filter((item) => serviceKey(item.finding_snapshot?.service as string | undefined) === selected) : cases;
}
