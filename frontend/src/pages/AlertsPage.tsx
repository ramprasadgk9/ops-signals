import { Stack } from '@mui/material';
import { AlertsOverviewPanel } from '../components/AlertTimeline';
import { FeatureNeedsSource } from '../components/FeatureNeedsSource';
import { useFeatureAvailability } from '../hooks/useFeatureAvailability';
import { PageHeader } from '../standalone/components';

/** Received alerts: what fired, what changed just before (deploys), where (pods), and the finding
 * or case each one was linked to. Connecting alert sources lives on Integrations. */
export function AlertsPage() {
  const { status } = useFeatureAvailability();
  // Alerts received before enrichment was switched off stay worth showing.
  const hasHistory = Boolean(status?.sources.alertmanager.last_received_at);
  return (
    <Stack spacing={3}>
      <PageHeader title="Alerts" subtitle="Alerts received from Alertmanager and other sources, with what changed and where" />
      <FeatureNeedsSource feature="alert_enrichment" keepContent={hasHistory}>
        <AlertsOverviewPanel title="Received alerts" />
      </FeatureNeedsSource>
    </Stack>
  );
}
