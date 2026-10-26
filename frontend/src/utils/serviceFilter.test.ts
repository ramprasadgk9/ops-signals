import { describe, expect, it } from 'vitest';
import { casesInService, inService, NO_SERVICE_KEY, serviceKey, serviceOptions, showServiceFilter } from './serviceFilter';

const items = [
  { service: 'payments-api' },
  { service: 'checkout-api' },
  { service: 'checkout-api' },
  { service: 'unknown' },
  { service: 'unknown-service' },
  { service: null },
  { service: 'search-api' },
];

describe('serviceFilter', () => {
  it('groups every way of storing "no service" under one key', () => {
    expect(['unknown', 'unknown-service', 'n/a', '', null, undefined].map(serviceKey)).toEqual(Array(6).fill(NO_SERVICE_KEY));
    expect(serviceKey(' payments-api ')).toBe('payments-api');
  });

  it('lists services busiest first, then by name, with no service last', () => {
    expect(serviceOptions(items)).toEqual([
      { key: 'checkout-api', label: 'checkout-api', count: 2 },
      { key: 'payments-api', label: 'payments-api', count: 1 },
      { key: 'search-api', label: 'search-api', count: 1 },
      { key: NO_SERVICE_KEY, label: 'No service label', count: 3 },
    ]);
  });

  it('keeps a selected service that has nothing in the list', () => {
    expect(serviceOptions(items, 'billing-worker')).toContainEqual({ key: 'billing-worker', label: 'billing-worker', count: 0 });
  });

  it('filters by service, and by no service', () => {
    expect(inService(items, 'checkout-api')).toHaveLength(2);
    expect(inService(items, NO_SERVICE_KEY)).toHaveLength(3);
    expect(inService(items, null)).toHaveLength(items.length);
  });

  it('shows the filter only when there is a choice', () => {
    expect(showServiceFilter(serviceOptions([{ service: 'a' }]))).toBe(false);
    expect(showServiceFilter(serviceOptions([{ service: 'a' }]), 'a')).toBe(true);
    expect(showServiceFilter(serviceOptions([{ service: 'a' }, { service: 'b' }]))).toBe(true);
  });

  it('filters cases by the service in their finding snapshot', () => {
    const cases = [{ finding_snapshot: { service: 'payments-api' } }, { finding_snapshot: {} }, { finding_snapshot: null }];
    expect(casesInService(cases, 'payments-api')).toHaveLength(1);
    expect(casesInService(cases, NO_SERVICE_KEY)).toHaveLength(2);
    expect(casesInService(cases, null)).toHaveLength(3);
  });
});
