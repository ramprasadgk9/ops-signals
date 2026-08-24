import { Box, Stack } from '@mui/material';
import { useQueryClient } from '@tanstack/react-query';
import { AutonomousConfigurePanel } from '../autonomous/AutonomousConfigurePanel';
import { PageHeader } from '../standalone/components';

export function AutonomousMonitoringPage() {
  const queryClient = useQueryClient();
  const refreshAutonomousData = () => {
    void queryClient.invalidateQueries({ queryKey: ['overview-autonomous-policy-runs'] });
    void queryClient.invalidateQueries({ queryKey: ['autonomous-policy-runs'] });
    void queryClient.invalidateQueries({ queryKey: ['findings-overview', '24h'] });
  };

  return (
    <Box sx={{ mx: { xs: -2, md: 0 }, p: { xs: 1, md: 0 } }}>
      <Stack spacing={3}>
        <PageHeader title="Autonomous Analysis Configure" subtitle="Configure scope, monitoring categories, execution limits, and run autonomous analysis." />
        <AutonomousConfigurePanel onRunComplete={refreshAutonomousData} />
      </Stack>
    </Box>
  );
}
