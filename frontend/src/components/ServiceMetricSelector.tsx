import { FormControl, Grid2 as Grid, InputLabel, MenuItem, Select } from '@mui/material';

type Props = {
  service: string;
  metric: string;
  services: string[];
  metrics: string[];
  onService: (value: string) => void;
  onMetric: (value: string) => void;
};

export function ServiceMetricSelector({ service, metric, services, metrics, onService, onMetric }: Props) {
  return (
    <Grid container spacing={2}>
      <Grid size={{ xs: 12, md: 6 }}>
        <FormControl fullWidth>
          <InputLabel>Service</InputLabel>
          <Select value={service} label="Service" onChange={(e) => onService(e.target.value)}>
            {services.map((item) => (
              <MenuItem key={item} value={item}>{item}</MenuItem>
            ))}
          </Select>
        </FormControl>
      </Grid>
      <Grid size={{ xs: 12, md: 6 }}>
        <FormControl fullWidth>
          <InputLabel>Metric</InputLabel>
          <Select value={metric} label="Metric" onChange={(e) => onMetric(e.target.value)}>
            {metrics.map((item) => (
              <MenuItem key={item} value={item}>{item}</MenuItem>
            ))}
          </Select>
        </FormControl>
      </Grid>
    </Grid>
  );
}
