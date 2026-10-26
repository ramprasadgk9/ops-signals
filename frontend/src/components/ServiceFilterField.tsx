import { Autocomplete, Box, TextField, Typography } from '@mui/material';
import type { ServiceOption } from '../utils/serviceFilter';

const ALL: ServiceOption = { key: '', label: 'All services', count: 0 };

/** Searchable Service filter for Findings and Cases: a dropdown rather than chips, since there can
 * be hundreds of services. Counts are for what the page has loaded (the window, for Findings). */
export function ServiceFilterField({ options, value, total, onChange, sx }: {
  options: ServiceOption[];
  value: string | null;
  /** Count shown next to "All services". */
  total: number;
  onChange: (service: string | null) => void;
  sx?: object;
}) {
  const all = { ...ALL, count: total };
  const choices = [all, ...options];
  const selected = choices.find((option) => option.key === (value ?? '')) ?? all;
  return (
    <Autocomplete
      size="small"
      disableClearable
      options={choices}
      value={selected}
      onChange={(_, option) => onChange(option.key || null)}
      getOptionLabel={(option) => option.label}
      isOptionEqualToValue={(option, current) => option.key === current.key}
      renderOption={({ key, ...props }, option) => (
        <Box component="li" key={key} {...props} sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
          <span>{option.label}</span>
          <Typography component="span" variant="body2" sx={{ color: 'text.secondary' }}>{option.count}</Typography>
        </Box>
      )}
      renderInput={(params) => <TextField {...params} label="Service" inputProps={{ ...params.inputProps, 'aria-label': 'Service' }} />}
      sx={{ minWidth: 220, bgcolor: 'var(--os-surface)', ...sx }}
    />
  );
}
