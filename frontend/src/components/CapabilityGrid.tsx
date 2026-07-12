import { Grid2 as Grid, Typography } from '@mui/material';
import type { Capability } from '../types';
import { CapabilityCard } from './CapabilityCard';

type Props = {
  capabilities: Capability[];
};

export function CapabilityGrid({ capabilities }: Props) {
  return (
    <>
      <Typography variant="h5" sx={{ mb: 2 }}>Installed Intelligence Capabilities</Typography>
      <Grid container spacing={2}>
        {capabilities.map((capability) => (
          <Grid key={capability.id} size={{ xs: 12, md: 6, lg: 4 }}>
            <CapabilityCard capability={capability} />
          </Grid>
        ))}
      </Grid>
    </>
  );
}
