import { useQuery } from '@tanstack/react-query';
import { api } from './queries';

/** The display name of a Prometheus connection, or null when there is only one connection
 * (nothing to tell apart) or the id is unknown/absent (CSV, OTLP and older runs). */
export function useConnectionName(connectionId: string | null | undefined): string | null {
  const connectionsQuery = useQuery({
    queryKey: ['prometheus-connections'],
    queryFn: () => api.prometheusConnections(),
    enabled: Boolean(connectionId),
    retry: false,
    staleTime: 5 * 60 * 1000,
  });
  const connections = connectionsQuery.data?.connections ?? [];
  if (!connectionId || connections.length < 2) return null;
  return connections.find((connection) => connection.id === connectionId)?.name ?? connectionId;
}
