import { Box, Button, Typography } from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { Link as RouterLink } from 'react-router-dom';
import { api } from '../api/queries';
import { ui } from '../standalone/theme';
import { setupBanner } from '../utils/setupCheck';

// A reminder above Overview while something Ops Signals needs is broken; nothing at all otherwise,
// and nothing if the check itself fails (the rest of the page shows that the backend is down).
export function SetupBanner() {
  const query = useQuery({ queryKey: ['setup-check'], queryFn: api.setupCheck, retry: false, staleTime: 5 * 60_000 });
  const message = query.data ? setupBanner(query.data) : null;
  if (!message) return null;
  return (
    <Box
      role="status"
      sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 2, flexWrap: 'wrap', px: 2, py: 1.5, borderRadius: '8px', border: '1px solid rgba(245, 158, 11, 0.45)', bgcolor: 'rgba(245, 158, 11, 0.08)' }}
    >
      <Typography sx={{ fontSize: 14 }}>{message}</Typography>
      <Button component={RouterLink} to="/setup-check" size="small" variant="outlined" sx={{ textTransform: 'none', fontWeight: 750, color: ui.text, borderColor: ui.border }}>
        Open Setup check
      </Button>
    </Box>
  );
}
