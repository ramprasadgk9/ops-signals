import { Typography } from '@mui/material';

/** Why a button is locked for this person's role (hooks/useWebPermissions). */
export function LockNote({ children }: { children: string }) {
  return (
    <Typography variant="caption" component="p" sx={{ color: 'var(--os-ink-amber, #b45309)', fontWeight: 700, mt: 0.75 }}>
      {children}
    </Typography>
  );
}

/** The notice above an Admins-only page: Viewers and Editors may look, its actions are locked. */
export function AdminOnlyNotice() {
  return (
    <Typography
      role="note"
      sx={{ border: '1px solid var(--os-tint-amber-border, #fed7aa)', bgcolor: 'var(--os-tint-amber, #fff7ed)', color: 'var(--os-ink-amber, #b45309)', borderRadius: '8px', px: 2, py: 1.25, fontWeight: 700, fontSize: 14 }}
    >
      🔒 Admin area. You can look around; only Ops Signals admins can change things here.
    </Typography>
  );
}
