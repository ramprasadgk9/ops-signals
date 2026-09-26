import { Stack, Typography } from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { AlertsOverviewPanel } from '../components/AlertTimeline';
import { IntegrationTiles, SourceStatusStrip } from '../components/GetDataInPanel';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { OtlpIngestionCard } from '../components/OtlpIngestionCard';
import { PageHeader, WorkspacePanel } from '../standalone/components';

export function IntegrationsPage() {
  const statusQuery = useQuery({ queryKey: ['ingestion-status'], queryFn: () => api.ingestionStatus(), retry: false, refetchInterval: 15_000 });
  const status = statusQuery.data;

  return (
    <Stack spacing={3}>
      <PageHeader
        title="Integrations"
        subtitle="Everything that sends data into Ops Signals, and whether it is arriving"
        action={status ? <SourceStatusStrip status={status} /> : undefined}
      />

      {statusQuery.isLoading ? <LoadingSkeleton /> : null}
      {statusQuery.isError ? (
        <WorkspacePanel sx={{ p: 2.5 }}>
          <Typography color="text.secondary">Could not load integration status. The endpoints below still accept data.</Typography>
        </WorkspacePanel>
      ) : null}
      {status ? <IntegrationTiles status={status} /> : null}

      <AlertsOverviewPanel title="Alerts" />

      <OtlpIngestionCard showEndpoint={!status} />
    </Stack>
  );
}
