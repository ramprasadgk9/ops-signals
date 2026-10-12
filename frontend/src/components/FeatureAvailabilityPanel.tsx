import { useState } from 'react';
import { Box, Button, Chip, Drawer, IconButton, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography } from '@mui/material';
import CloseRoundedIcon from '@mui/icons-material/CloseRounded';
import ViewSidebarOutlinedIcon from '@mui/icons-material/ViewSidebarOutlined';
import { sourceList } from '../hooks/useFeatureAvailability';
import { ui } from '../standalone/theme';
import type { FeatureAvailability } from '../types';

const STATE_CHIP: Record<FeatureAvailability['state'], { label: string; bg: string; color: string }> = {
  on: { label: 'On', bg: 'var(--os-tint-green)', color: 'var(--os-ink-green)' },
  partly: { label: 'Partly', bg: 'var(--os-tint-amber)', color: '#92400e' },
  off: { label: 'Off', bg: 'var(--os-surface-alt)', color: 'var(--os-text-2)' },
};

function why(feature: FeatureAvailability): string | null {
  if (feature.state === 'off') return `Needs ${sourceList(feature.missing)}`;
  if (feature.state === 'partly') return feature.detail ?? (feature.missing.length ? `Better with ${sourceList(feature.missing)}` : null);
  return null;
}

/** "What works with my data?": every feature and whether the connected sources run it, in a side
 * panel so the Integrations page itself stays about connecting things. */
export function FeatureAvailabilityPanel({ features }: { features?: FeatureAvailability[] }) {
  const [open, setOpen] = useState(false);
  if (!features?.length) return null;
  const count = (state: FeatureAvailability['state']) => features.filter((feature) => feature.state === state).length;
  return (
    <>
      <Button
        onClick={() => setOpen(true)}
        startIcon={<ViewSidebarOutlinedIcon />}
        variant="outlined"
        size="small"
        aria-expanded={open}
        sx={{ textTransform: 'none', fontWeight: 750 }}
      >
        What works with my data?
      </Button>
      <Drawer anchor="right" open={open} onClose={() => setOpen(false)}>
        <Box component="section" aria-labelledby="feature-availability-title" sx={{ width: { xs: '100vw', sm: 440 }, p: 3, boxSizing: 'border-box' }}>
          <Stack direction="row" alignItems="center" justifyContent="space-between">
            <Typography id="feature-availability-title" component="h2" sx={{ fontSize: 18, fontWeight: 850 }}>
              What works with my data
            </Typography>
            <IconButton onClick={() => setOpen(false)} aria-label="Close">
              <CloseRoundedIcon />
            </IconButton>
          </Stack>
          <Typography variant="body2" sx={{ color: ui.muted, mb: 1.5 }}>
            Worked out from the sources connected now. Nothing to configure.
          </Typography>
          <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
            {(['on', 'partly', 'off'] as const).map((state) =>
              count(state) ? (
                <Chip key={state} size="small" label={`${count(state)} ${STATE_CHIP[state].label.toLowerCase()}`} sx={{ bgcolor: STATE_CHIP[state].bg, color: STATE_CHIP[state].color, fontWeight: 750 }} />
              ) : null
            )}
          </Stack>
          <Table size="small" aria-label="Feature availability">
            <TableHead>
              <TableRow>
                <TableCell sx={{ fontWeight: 800 }}>Feature</TableCell>
                <TableCell sx={{ fontWeight: 800 }}>Status</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {features.map((feature) => (
                <TableRow key={feature.id} data-testid={`feature-row-${feature.id}`}>
                  <TableCell>{feature.label}</TableCell>
                  <TableCell>
                    <Chip size="small" label={STATE_CHIP[feature.state].label} sx={{ bgcolor: STATE_CHIP[feature.state].bg, color: STATE_CHIP[feature.state].color, fontWeight: 750 }} />
                    {why(feature) ? (
                      <Typography variant="caption" component="div" sx={{ color: 'var(--os-text-2)', mt: 0.5 }}>
                        {why(feature)}
                      </Typography>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      </Drawer>
    </>
  );
}
