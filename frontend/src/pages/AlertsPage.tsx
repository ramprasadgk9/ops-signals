import { Stack } from '@mui/material';
import { AlertsOverviewPanel } from '../components/AlertTimeline';
import { PageHeader } from '../standalone/components';

/** Received alerts: what fired, what changed just before (deploys), where (pods), and the finding
 * or case each one was linked to. Connecting alert sources lives on Integrations. */
export function AlertsPage() {
  return (
    <Stack spacing={3}>
      <PageHeader title="Alerts" subtitle="Alerts received from Alertmanager and other sources, with what changed and where" />
      <AlertsOverviewPanel title="Received alerts" />
    </Stack>
  );
}
