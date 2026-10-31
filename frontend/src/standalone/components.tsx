import type { ReactNode } from 'react';
import { Box, Button, Chip, Stack, Typography } from '@mui/material';
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded';
import { Link as RouterLink } from 'react-router-dom';
import { panelSx, severityTone, statusTone, titleCase, ui } from './theme';

export function PageHeader({
  title,
  subtitle,
  help,
  action,
}: {
  title: string;
  subtitle: string;
  /** Shown at the end of the subtitle, e.g. <WhatsWhat page="cases" />. */
  help?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', md: 'center' }} spacing={2}>
      <Box>
        <Typography variant="h4" sx={{ fontSize: 28, fontWeight: 800, color: ui.text, letterSpacing: 0 }}>
          {title}
        </Typography>
        <Typography variant="body2" sx={{ mt: 0.75, color: ui.muted, fontWeight: 500 }}>
          {subtitle}
          {help}
        </Typography>
      </Box>
      {action}
    </Stack>
  );
}

export function WorkspacePanel({ children, sx }: { children: ReactNode; sx?: object }) {
  return <Box sx={{ ...panelSx, ...sx }}>{children}</Box>;
}

export function SectionHeader({ title, to }: { title: string; to?: string }) {
  return (
    <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 2 }}>
      <Typography variant="h6" sx={{ fontSize: 18, fontWeight: 800 }}>
        {title}
      </Typography>
      {to ? (
        <Button component={RouterLink} to={to} endIcon={<ArrowForwardRoundedIcon />} size="small" sx={{ color: ui.purple, textTransform: 'none', fontWeight: 750 }}>
          View all
        </Button>
      ) : null}
    </Stack>
  );
}

export function Pill({ label, tone = 'status' }: { label: string; tone?: 'severity' | 'status' }) {
  const colors = tone === 'severity' ? severityTone(label) : statusTone(label);
  return (
    <Chip
      label={titleCase(label)}
      size="small"
      sx={{
        height: 24,
        bgcolor: colors.bg,
        color: colors.color,
        border: `1px solid ${colors.border}`,
        fontWeight: 800,
        fontSize: 12,
      }}
    />
  );
}

export function IconTile({ children, bg, color }: { children: ReactNode; bg: string; color: string }) {
  return (
    <Box sx={{ width: 54, height: 54, borderRadius: '8px', bgcolor: bg, color, display: 'grid', placeItems: 'center', flex: '0 0 auto' }}>
      {children}
    </Box>
  );
}
