import { Box, Card, CardContent, Grid2 as Grid, Stack, Typography } from '@mui/material';
import type { AnalysisRun } from '../types';

type Props = {
  run: AnalysisRun | null;
};

export function CurrentAnalysisContext({ run }: Props) {
  if (!run) return null;

  const comparisionStart = new Date(run.start_time);
  comparisionStart.setDate(comparisionStart.getDate() - (Math.ceil((new Date(run.end_time).getTime() - new Date(run.start_time).getTime()) / (1000 * 60 * 60 * 24))));

  return (
    <Card>
      <CardContent>
        <Typography variant="h6" sx={{ mb: 2 }}>Current Analysis Context</Typography>

        <Grid container spacing={3}>
          <Grid size={{ xs: 12, sm: 6 }}>
            <Stack spacing={2}>
              <Box>
                <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>Service</Typography>
                <Typography variant="body2" sx={{ fontWeight: 500 }}>{run.service}</Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>Metric</Typography>
                <Typography variant="body2" sx={{ fontWeight: 500 }}>{run.metric_name}</Typography>
              </Box>
            </Stack>
          </Grid>

          <Grid size={{ xs: 12, sm: 6 }}>
            <Stack spacing={2}>
              <Box>
                <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>Samples</Typography>
                <Typography variant="body2" sx={{ fontWeight: 500 }}>{run.sample_count}</Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>Provider</Typography>
                <Typography variant="body2" sx={{ fontWeight: 500 }}>{run.provider}</Typography>
              </Box>
            </Stack>
          </Grid>

          <Grid size={{ xs: 12 }}>
            <Box>
              <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>Comparison Window</Typography>
              <Typography variant="body2" sx={{ fontWeight: 500 }}>
                {comparisionStart.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} – {new Date(run.start_time).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
              </Typography>
            </Box>
          </Grid>
        </Grid>
      </CardContent>
    </Card>
  );
}
