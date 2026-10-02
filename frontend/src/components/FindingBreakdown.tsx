import { Box, Chip, Stack, Typography } from '@mui/material';
import {
  breakdownNextStep,
  breakdownScopeLabel,
  breakdownSentence,
  breakdownSpreadColor,
  breakdownUnavailableReason,
  formatValue,
  type BreakdownPart,
  type FindingBreakdown as Breakdown,
} from '../utils/findingBreakdown';
import { deployNextStep, podLinkText, type FindingChanges } from '../utils/findingChanges';

type Props = {
  breakdown: Breakdown;
  /** Deploys near the change, when the backend sent them: links the new pods to a deploy. */
  changes?: FindingChanges | null;
};

function barWidth(part: BreakdownPart, breakdown: Breakdown, largest: number): number {
  if (breakdown.mode === 'share') return Math.max(0, Math.min(1, part.share ?? 0)) * 100;
  if (largest === 0 || part.relative_change === null) return 0;
  return Math.max(0, Math.min(1, Math.abs(part.relative_change) / largest)) * 100;
}

function barValue(part: BreakdownPart, breakdown: Breakdown): string {
  if (breakdown.mode === 'share') return `${Math.round((part.share ?? 0) * 100)}%`;
  if (part.relative_change === null) return '–';
  const sign = part.relative_change > 0 ? '+' : '';
  return `${sign}${Math.round(part.relative_change * 100)}%`;
}

/** "Where the change came from": the finding's per-pod breakdown, or why there isn't one. */
export function FindingBreakdown({ breakdown, changes = null }: Props) {
  if (breakdown.status !== 'ok') {
    return (
      <Box sx={{ mb: 3, p: 1.5, border: 1, borderColor: 'divider', borderStyle: 'dashed', borderRadius: 1 }}>
        <Typography variant="caption" color="text.secondary">
          Breakdown by pod not available: {breakdownUnavailableReason(breakdown)}
        </Typography>
      </Box>
    );
  }

  const parts = breakdown.top ?? [];
  const largest = Math.max(0, ...parts.map((part) => Math.abs(part.relative_change ?? 0)));
  const scope = breakdownScopeLabel(breakdown);
  const label = breakdown.label ?? 'pod';
  const podLink = podLinkText(changes);

  return (
    <Box sx={{ mb: 3, p: 2, borderRadius: 1, bgcolor: 'action.hover' }} data-testid="finding-breakdown">
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1, flexWrap: 'wrap', gap: 1 }}>
        <Typography variant="subtitle2">Where the change came from</Typography>
        {scope && <Chip size="small" label={scope} color={breakdownSpreadColor(breakdown)} />}
      </Stack>
      <Typography variant="body2" sx={{ mb: podLink ? 0.5 : 1.5 }}>{breakdownSentence(breakdown)}</Typography>
      {podLink && (
        <Box sx={{ mb: 1.5 }} data-testid="breakdown-deploy-link">
          <Typography variant="body2">{podLink.sentence}</Typography>
          {podLink.detail && (
            <Typography variant="caption" color="text.secondary">{podLink.detail}</Typography>
          )}
        </Box>
      )}

      <Stack spacing={0.75}>
        {parts.map((part) => (
          <Box
            key={part.value}
            sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 150px) 1fr 52px', alignItems: 'center', gap: 1 }}
            title={`${label} ${part.value}: ${formatValue(part.before)} → ${formatValue(part.after)}`}
          >
            <Typography variant="caption" sx={{ fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {part.value}{part.new ? ' ✦' : ''}
            </Typography>
            <Box sx={{ height: 10, borderRadius: 1, bgcolor: 'action.selected', overflow: 'hidden' }}>
              <Box
                sx={{
                  height: '100%',
                  width: `${barWidth(part, breakdown, largest)}%`,
                  bgcolor: part.moved ? 'error.main' : 'text.disabled',
                  borderRadius: 1,
                }}
              />
            </Box>
            <Typography variant="caption" color="text.secondary" sx={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
              {barValue(part, breakdown)}
            </Typography>
          </Box>
        ))}
        {breakdown.others && breakdown.others.count > 0 && (
          <Typography variant="caption" color="text.secondary">
            + {breakdown.others.count} other {breakdown.others.count === 1 ? label : `${label}s`}
            {breakdown.others.moved > 0 ? `, ${breakdown.others.moved} of them also changed` : ', unchanged'}
          </Typography>
        )}
      </Stack>

      {parts.some((part) => part.new) && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
          {'✦'} new {label}: no data before the change
        </Typography>
      )}
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
        {breakdown.mode === 'share' ? 'Bars: share of the total change.' : `Bars: change compared with each ${label}’s own normal level.`}
      </Typography>

      <Typography variant="body2" sx={{ mt: 1.5 }}>
        <strong>Likely next step:</strong> {breakdownNextStep(breakdown, deployNextStep(changes))}
      </Typography>
    </Box>
  );
}
