import { Chip, Stack, Typography } from '@mui/material';
import { ui } from '../standalone/theme';
import type { Novelty } from '../types';

const COLORS: Record<Novelty['level'], 'info' | 'default' | 'warning'> = {
  new: 'info',
  new_on_service: 'info',
  seen_before: 'default',
  recurring: 'warning',
};

/** "New pattern" / "Seen before" / "Recurring · N past cases", with the reason underneath, so on-call
 * can tell a first occurrence from a problem with history at a glance. */
export function NoveltyBadge({ novelty }: { novelty?: Novelty | null }) {
  if (!novelty) return null;
  return (
    <Stack spacing={0.5} sx={{ mb: 1.5 }} data-testid="novelty-badge">
      <Chip
        size="small"
        label={novelty.label}
        color={COLORS[novelty.level]}
        variant={novelty.level === 'seen_before' ? 'outlined' : 'filled'}
        sx={{ alignSelf: 'flex-start', fontWeight: 800 }}
      />
      <Typography sx={{ fontSize: 13, color: ui.muted }}>{novelty.explanation}</Typography>
    </Stack>
  );
}
