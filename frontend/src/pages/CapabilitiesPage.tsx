import { Box, Typography } from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { CapabilityGrid } from '../components/CapabilityGrid';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { ErrorState } from '../components/ErrorState';

export function CapabilitiesPage() {
  const query = useQuery({ queryKey: ['capabilities'], queryFn: api.capabilities });
  if (query.isLoading) return <LoadingSkeleton />;
  if (query.error) return <ErrorState message="Failed to load capabilities" />;

  const enabled = (query.data ?? []).filter((c) => c.enabled);
  const disabled = (query.data ?? []).filter((c) => !c.enabled);

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <Box>
        <Typography variant="h4" sx={{ mb: 1 }}>Capabilities</Typography>
        <Typography variant="body2" color="text.secondary">
          Analysis capabilities power operational intelligence. Each capability registers supported question IDs and produces signals.
        </Typography>
      </Box>

      {enabled.length > 0 && (
        <Box>
          <Typography variant="h6" sx={{ mb: 2 }}>Active Capabilities</Typography>
          <CapabilityGrid capabilities={enabled} />
        </Box>
      )}

      {disabled.length > 0 && (
        <Box>
          <Typography variant="h6" sx={{ mb: 2 }}>Available Capabilities</Typography>
          <CapabilityGrid capabilities={disabled} />
        </Box>
      )}
    </Box>
  );
}
