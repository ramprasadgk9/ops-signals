import { useState } from 'react';
import { Box, Button, Chip, Divider, Popover, Stack, Tooltip, Typography } from '@mui/material';
import KeyboardArrowDownRoundedIcon from '@mui/icons-material/KeyboardArrowDownRounded';
import { useMutation } from '@tanstack/react-query';
import { api } from '../api/queries';
import { useWebPermissions } from '../hooks/useWebPermissions';
import { useDemo } from '../demo/demo';

const VIA_LABEL: Record<string, string> = { proxy: 'company sign-in', oidc: 'your company account', grafana: 'Grafana', dev: 'OPS_SIGNALS_DEV_USER (dev only)' };

/** "7 h 12 min" until the session ends, or null without one. */
export function timeLeft(endsAt: string | null | undefined, now: number = Date.now()): string | null {
  if (!endsAt) return null;
  const minutes = Math.max(0, Math.round((new Date(endsAt).getTime() - now) / 60_000));
  if (Number.isNaN(minutes)) return null;
  const hours = Math.floor(minutes / 60);
  return hours ? `${hours} h ${minutes % 60} min` : `${minutes} min`;
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <Stack direction="row" justifyContent="space-between" spacing={2} sx={{ py: 0.4 }}>
      <Typography variant="body2" color="text.secondary">{label}</Typography>
      <Typography variant="body2" sx={{ fontWeight: 800, textAlign: 'right' }}>{value}</Typography>
    </Stack>
  );
}

/** Top right of the web UI: who is signed in and their role, or that nobody is (and so nothing is limited). */
export function UserChip() {
  const { me, role } = useWebPermissions();
  const demo = useDemo();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  // The backend clears the session and says where to go: the provider's sign-out, or /signed-out.
  const signOut = useMutation({ mutationFn: api.signOut, onSuccess: ({ redirect }) => window.location.assign(redirect) });
  if (!me) return null;

  if (role === null && demo) {
    return (
      <Tooltip title="Anyone can look around, open cases and try the steps. Settings that would change the site for everyone are view-only.">
        <Chip label="Demo visitor" size="small" sx={{ fontWeight: 800 }} data-testid="demo-visitor" />
      </Tooltip>
    );
  }

  if (role === null) {
    const label = me.problem ? 'Sign-in problem · see Setup check' : 'Not signed in · everyone can change things';
    return (
      <>
        <Chip
          clickable
          onClick={(event) => setAnchor(event.currentTarget)}
          aria-label={label}
          label={
            <Stack direction="row" alignItems="center" spacing={0.5}>
              <span>{label}</span>
              <KeyboardArrowDownRoundedIcon sx={{ fontSize: 18 }} />
            </Stack>
          }
          sx={{ bgcolor: 'var(--os-tint-amber, #fff7ed)', color: 'var(--os-ink-amber, #b45309)', border: '1px solid var(--os-tint-amber-border, #fed7aa)', fontWeight: 700 }}
        />
        <Popover open={Boolean(anchor)} anchorEl={anchor} onClose={() => setAnchor(null)} anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }} transformOrigin={{ vertical: 'top', horizontal: 'right' }}>
          <Box sx={{ p: 2, width: 320 }}>
            <Typography variant="body2" sx={{ mb: 1.5 }}>
              {me.problem ?? 'Nobody signs in to this web UI yet, so there are no roles and no names on what people do.'}
            </Typography>
            {/* Without sign-in every page is open, so whoever reads this can open Setup check. */}
            <Button size="small" variant="contained" disableElevation href="/setup-check" sx={{ textTransform: 'none', fontWeight: 750 }}>
              {me.problem ? 'Open Setup check' : 'Set up sign-in on Setup check'}
            </Button>
          </Box>
        </Popover>
      </>
    );
  }

  const name = me.name ?? 'anonymous';
  const label = `${name.split('@')[0]} · ${role}${me.via === 'dev' ? ' (dev)' : ''}`;
  return (
    <>
      <Chip
        clickable
        onClick={(event) => setAnchor(event.currentTarget)}
        aria-label={`Signed in as ${name}, ${role}`}
        label={
          <Stack direction="row" alignItems="center" spacing={0.5}>
            <span>{label}</span>
            <KeyboardArrowDownRoundedIcon sx={{ fontSize: 18 }} />
          </Stack>
        }
        avatar={<Box component="span" sx={{ bgcolor: '#60a5fa !important', color: '#fff !important', fontWeight: 800 }}>{name.charAt(0).toUpperCase()}</Box>}
        sx={{ bgcolor: '#eef2ff', color: '#3730a3', border: '1px solid #c7d2fe', fontWeight: 700 }}
      />
      <Popover open={Boolean(anchor)} anchorEl={anchor} onClose={() => setAnchor(null)} anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }} transformOrigin={{ vertical: 'top', horizontal: 'right' }}>
        <Box sx={{ p: 2, width: 300 }}>
          <Row label="Signed in as" value={name} />
          <Row label="Role" value={role} />
          {me.granted_by ? <Row label="Because of group" value={me.granted_by} /> : null}
          <Row label="Through" value={VIA_LABEL[me.via] ?? me.via} />
          {timeLeft(me.session_ends_at) ? <Row label="Session ends in" value={timeLeft(me.session_ends_at)!} /> : null}
          {me.via === 'oidc' ? (
            <Box sx={{ py: 0.4 }}>
              <Typography variant="body2" color="text.secondary">Groups your provider sent</Typography>
              <Typography variant="body2" sx={{ fontWeight: 700, fontFamily: 'ui-monospace, Menlo, monospace', fontSize: 12.5, overflowWrap: 'anywhere' }}>
                {me.arrived_groups?.length ? me.arrived_groups.join(', ') : 'none'}
              </Typography>
            </Box>
          ) : null}
          <Typography variant="caption" color="text.secondary" component="p" sx={{ mt: 1 }}>
            Roles come from your company's groups. Ask your Ops Signals admin to change yours.
            {me.via === 'oidc' ? ' When the session ends, you sign in again.' : ''}
          </Typography>
          {me.via === 'oidc' ? (
            <>
              <Divider sx={{ my: 1.5 }} />
              <Button size="small" variant="outlined" disabled={signOut.isPending} onClick={() => signOut.mutate()} sx={{ textTransform: 'none', fontWeight: 750 }}>
                {signOut.isPending ? 'Signing out…' : 'Sign out'}
              </Button>
            </>
          ) : null}
        </Box>
      </Popover>
    </>
  );
}
