import type { ReactNode } from 'react';
import { Box, Button, Stack, Typography } from '@mui/material';
import LockOutlinedIcon from '@mui/icons-material/LockOutlined';
import { Link as RouterLink, useLocation } from 'react-router-dom';
import { useWebPermissions } from '../hooks/useWebPermissions';

/** A page that only some roles may open (backend/app/roles.py PAGES). Anyone else gets a note saying
 * who may and whom to ask, and the page itself never loads. Waits for GET /api/me, so a closed page
 * doesn't flash up first. */
export function RoleArea({ name, children }: { name: string; children: ReactNode }) {
  const { pathname } = useLocation();
  const { me, loading, neededFor } = useWebPermissions();
  if (loading) return null;
  const needed = neededFor(pathname);
  if (!needed) return <>{children}</>;
  const who = me?.name ? `You're signed in as ${me.name.split('@')[0]} (${me.role}).` : '';
  const ask = needed === 'Admin'
    ? 'Ask your Ops Signals admin if you need it.'
    : 'Ask your Ops Signals admin for the Editor role.';
  return (
    <Box role="alert" sx={{ display: 'grid', placeItems: 'center', py: { xs: 6, md: 10 } }}>
      <Stack spacing={1.5} alignItems="center" sx={{ maxWidth: 460, textAlign: 'center' }}>
        <LockOutlinedIcon sx={{ fontSize: 40, color: 'var(--os-ink-amber, #b45309)' }} />
        <Typography variant="h5" sx={{ fontWeight: 850 }}>
          {name} is for {needed === 'Admin' ? 'Ops Signals admins' : 'Editors'}
        </Typography>
        <Typography color="text.secondary">{[who, ask].filter(Boolean).join(' ')}</Typography>
        <Button component={RouterLink} to="/" variant="contained" sx={{ textTransform: 'none', fontWeight: 800 }}>
          Go to Overview
        </Button>
      </Stack>
    </Box>
  );
}
