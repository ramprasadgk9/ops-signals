import type { Finding, PrometheusConnection } from '../types';

// Where a finding's data came from: its cluster (several clusters behind one Mimir or Thanos) and its
// Prometheus connection (one per Mimir tenant). Worded like the web UI's finding card, which names
// the connection only when there is more than one (api/useConnectionName).

/** The connection's display name, or null when there is only one connection or none is recorded. */
export function connectionName(connections: PrometheusConnection[], connectionId?: string | null): string | null {
  if (!connectionId || connections.length < 2) return null;
  return connections.find((connection) => connection.id === connectionId)?.name ?? connectionId;
}

/** "us · Team A", "us", or null for single-cluster data on the only connection. */
export function findingSource(finding: Pick<Finding, 'cluster' | 'connection_id'>, connections: PrometheusConnection[]): string | null {
  const parts = [finding.cluster, connectionName(connections, finding.connection_id)].filter(Boolean);
  return parts.length ? parts.join(' · ') : null;
}

/** Clusters present in `findings`, sorted; empty for single-cluster data. */
export function findingClusters(findings: Array<Pick<Finding, 'cluster'>>): string[] {
  return [...new Set(findings.map((finding) => finding.cluster).filter((cluster): cluster is string => Boolean(cluster)))].sort();
}

/** Findings in `cluster`, or all of them when it is null or no longer among their clusters. */
export function findingsInCluster<T extends Pick<Finding, 'cluster'>>(findings: T[], cluster: string | null): { cluster: string | null; findings: T[] } {
  const active = cluster && findingClusters(findings).includes(cluster) ? cluster : null;
  return { cluster: active, findings: active ? findings.filter((finding) => finding.cluster === active) : findings };
}
