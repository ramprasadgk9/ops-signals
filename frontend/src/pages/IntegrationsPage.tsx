import { Stack, Typography } from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { AiProviderCard } from '../components/AiProviderCard';
import { FeatureAvailabilityPanel } from '../components/FeatureAvailabilityPanel';
import { IntegrationTiles, OneOffAnalysisLine, SourceStatusStrip } from '../components/GetDataInPanel';
import { ImportHistoryCard } from '../components/ImportHistoryCard';
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
        action={
          status ? (
            <Stack spacing={1} alignItems={{ xs: 'flex-start', md: 'flex-end' }}>
              <SourceStatusStrip status={status} />
              <FeatureAvailabilityPanel features={status.features} />
            </Stack>
          ) : undefined
        }
      />

      {statusQuery.isLoading ? <LoadingSkeleton /> : null}
      {statusQuery.isError ? (
        <WorkspacePanel sx={{ p: 2.5 }}>
          <Typography color="text.secondary">Could not load integration status. The endpoints below still accept data.</Typography>
        </WorkspacePanel>
      ) : null}
      {status ? <IntegrationTiles status={status} exploring={false} /> : null}

      {/* Without the tiles, this card is the one place left that shows the OTLP endpoint. */}
      {statusQuery.isError ? <OtlpIngestionCard /> : null}

      <ImportHistoryCard />

      <AiProviderCard />

      <OneOffAnalysisLine />
    </Stack>
  );
}
