import { Typography } from '@mui/material';

/** Why a button is locked for this person's role (hooks/useWebPermissions). */
export function LockNote({ children }: { children: string }) {
  return (
    <Typography variant="caption" component="p" sx={{ color: 'var(--os-ink-amber, #b45309)', fontWeight: 700, mt: 0.75 }}>
      {children}
    </Typography>
  );
}

