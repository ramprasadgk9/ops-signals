import { describe, expect, it } from 'vitest';
import type { PrometheusConnection } from '../types';
import { connectionName, findingClusters, findingSource, findingsInCluster } from './findingSource';

const ONE: PrometheusConnection[] = [{ id: 'default', name: 'Default Prometheus', configured: true, is_default: true }];
const TWO: PrometheusConnection[] = [...ONE, { id: 'team-a', name: 'Team A (Mimir)', configured: true }];

describe('findingSource', () => {
  it('names the connection only when there are several, as the web UI does', () => {
    expect(connectionName(ONE, 'default')).toBeNull();
    expect(connectionName(TWO, 'team-a')).toBe('Team A (Mimir)');
    expect(connectionName(TWO, 'gone')).toBe('gone');
    expect(connectionName(TWO, null)).toBeNull();
  });

  it('says where a finding came from: cluster, then connection', () => {
    expect(findingSource({ cluster: 'us', connection_id: 'team-a' }, TWO)).toBe('us · Team A (Mimir)');
    expect(findingSource({ cluster: 'us', connection_id: 'default' }, ONE)).toBe('us');
    expect(findingSource({ cluster: null, connection_id: null }, ONE)).toBeNull();
  });

  it('lists clusters and filters to one, falling back to all when the cluster is gone', () => {
    const findings = [{ cluster: 'us' }, { cluster: 'eu' }, { cluster: null }, { cluster: 'us' }];

    expect(findingClusters(findings)).toEqual(['eu', 'us']);
    expect(findingsInCluster(findings, 'us')).toEqual({ cluster: 'us', findings: [{ cluster: 'us' }, { cluster: 'us' }] });
    expect(findingsInCluster(findings, 'staging')).toEqual({ cluster: null, findings });
    expect(findingsInCluster(findings, null).findings).toHaveLength(4);
  });
});
