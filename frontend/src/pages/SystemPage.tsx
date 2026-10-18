import { Button, Grid2 as Grid, Stack, Typography } from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { PageHeader, Pill, WorkspacePanel } from '../standalone/components';
import { ui } from '../standalone/theme';

export function SystemPage() {
  const healthQuery = useQuery({ queryKey: ['system-health'], queryFn: api.health, retry: false });
  const memoryQuery = useQuery({ queryKey: ['system-memory-health'], queryFn: api.memoryHealth, retry: false });
  const services = [
    { name: 'Backend', status: healthQuery.isError ? 'unavailable' : healthQuery.isLoading ? 'loading' : healthQuery.data ? 'ok' : 'unknown', detail: 'Source: GET /api/health', retry: () => healthQuery.refetch() },
    { name: 'Qdrant', status: memoryQuery.isError ? 'unavailable' : memoryQuery.isLoading ? 'loading' : memoryQuery.data?.status ?? 'unknown', detail: memoryQuery.data?.detail ?? 'Source: GET /api/memory/health', retry: () => memoryQuery.refetch() },
    { name: 'Database', status: healthQuery.isError ? 'unknown' : healthQuery.isLoading ? 'loading' : healthQuery.data?.database ?? 'unknown', detail: 'Source: GET /api/health (checks the database on every call)', retry: () => healthQuery.refetch() },
    { name: 'MCP Server', status: 'separate process', detail: 'Your AI client starts the MCP server itself (stdio), so it has no health check here. Its HTTP tools (/api/mcp) are part of this backend and answer whenever Backend is ok.' },
  ];
  return (
    <Stack spacing={3}>
      <PageHeader title="System" subtitle="Runtime health for the standalone workspace" />
      <Grid container spacing={2}>
        {services.map((service) => (
          <Grid key={service.name} size={{ xs: 12, md: 6, lg: 3 }}>
            <WorkspacePanel sx={{ p: 2.5 }}>
              <Stack direction="row" alignItems="center" justifyContent="space-between">
                <Typography sx={{ fontWeight: 900 }}>{service.name}</Typography>
                <Pill label={service.status} />
              </Stack>
              <Typography sx={{ color: ui.muted, mt: 1.5 }}>{service.detail}</Typography>
              {service.retry ? <Button onClick={() => service.retry?.()} sx={{ mt: 1.5, textTransform: 'none', fontWeight: 800 }}>Retry</Button> : null}
            </WorkspacePanel>
          </Grid>
        ))}
      </Grid>
    </Stack>
  );
}
