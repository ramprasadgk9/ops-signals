import { useState } from 'react';
import { Box, Chip, Popover, Stack, Tooltip, Typography } from '@mui/material';
import KeyboardArrowDownRoundedIcon from '@mui/icons-material/KeyboardArrowDownRounded';
import { useWebPermissions } from '../hooks/useWebPermissions';

const VIA_LABEL: Record<string, string> = { proxy: 'company sign-in', grafana: 'Grafana', dev: 'OPS_SIGNALS_DEV_USER (dev only)' };

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
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  if (!me) return null;

  if (role === null) {
    return (
      <Tooltip title={me.problem ?? 'No sign-in is set up, so the web UI has no roles. See Setup check → Login.'}>
        <Chip
          label={me.problem ? 'Sign-in problem · see Setup check' : 'Not signed in · everyone can change things'}
          sx={{ bgcolor: 'var(--os-tint-amber, #fff7ed)', color: 'var(--os-ink-amber, #b45309)', border: '1px solid var(--os-tint-amber-border, #fed7aa)', fontWeight: 700 }}
        />
      </Tooltip>
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
          <Typography variant="caption" color="text.secondary" component="p" sx={{ mt: 1 }}>
            Roles come from your company's groups. Ask your Ops Signals admin to change yours.
          </Typography>
        </Box>
      </Popover>
    </>
  );
}
