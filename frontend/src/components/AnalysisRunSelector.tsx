import { Box, Card, CardContent, FormControl, Grid2 as Grid, InputLabel, MenuItem, Select, Stack, Typography } from '@mui/material';
import type { AnalysisRun } from '../types';

type Props = {
  runs: AnalysisRun[];
  value: string;
  onChange: (id: string) => void;
};

export function AnalysisRunSelector({ runs, value, onChange }: Props) {
  const selectedRun = runs.find((r) => r.id === value);

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  return (
    <Card>
      <CardContent>
        <Typography variant="h6" sx={{ mb: 2 }}>Analysis Run</Typography>

        <FormControl fullWidth sx={{ mb: 2 }}>
          <InputLabel>Select Analysis Run</InputLabel>
          <Select 
            value={value} 
            label="Select Analysis Run" 
            onChange={(e) => onChange(e.target.value)}
          >
            {runs.map((run) => (
              <MenuItem key={run.id} value={run.id}>
                {formatDate(run.start_time)} - {formatDate(run.end_time)} ({run.sample_count} samples)
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        {selectedRun && (
          <Grid container spacing={2}>
            <Grid size={{ xs: 6 }}>
              <Box>
                <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>Start</Typography>
                <Typography variant="body2" sx={{ fontWeight: 500 }}>
                  {formatDate(selectedRun.start_time)}
                </Typography>
              </Box>
            </Grid>
            <Grid size={{ xs: 6 }}>
              <Box>
                <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>End</Typography>
                <Typography variant="body2" sx={{ fontWeight: 500 }}>
                  {formatDate(selectedRun.end_time)}
                </Typography>
              </Box>
            </Grid>
          </Grid>
        )}
      </CardContent>
    </Card>
  );
}
