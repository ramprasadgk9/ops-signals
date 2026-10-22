import { Box, Chip, Stack, Tooltip, Typography } from '@mui/material';
import type { BehaviorFinding } from '../types';
import { conditionsPassed, formatChange, overlapMinutes, parseUtc, patternParts } from '../utils/combinedPatterns';

// Told apart by lightness as well as hue, so the metric dots still read without color.
const PART_COLORS = ['#0d9488', '#d97706', '#7c3aed', '#2563eb'];

function clock(value: string | null): string | null {
  const time = parseUtc(value);
  return Number.isFinite(time) ? new Date(time).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : null;
}

/** Each metric a combined pattern matched on, with its shape, change and window. */
export function PatternMetrics({ behavior }: { behavior: BehaviorFinding }) {
  return (
    <Stack spacing={0.75} aria-label="Metrics in this pattern">
      {patternParts(behavior).map((part, index) => {
        const change = formatChange(part.change);
        const start = clock(part.start);
        const end = clock(part.end);
        return (
          <Stack key={part.alias} direction="row" alignItems="center" spacing={1.25} useFlexGap flexWrap="wrap" sx={{ px: 1.25, py: 0.9, borderRadius: '8px', bgcolor: 'var(--os-surface-alt)' }}>
            <Box aria-hidden sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: PART_COLORS[index % PART_COLORS.length], flexShrink: 0 }} />
            <Typography variant="body2" sx={{ fontFamily: 'monospace', fontWeight: 700, flex: '1 1 220px', minWidth: 0, overflowWrap: 'anywhere' }}>
              {part.metric}
            </Typography>
            <Typography variant="body2">{part.shape}</Typography>
            {change ? <Typography variant="body2" sx={{ fontWeight: 800 }}>{change}</Typography> : null}
            {start && end ? <Typography variant="caption" color="text.secondary">{start} – {end}</Typography> : null}
          </Stack>
        );
      })}
    </Stack>
  );
}

/** Why the pattern matched: the timing check, the conditions, and how often it was seen. */
export function PatternWhy({ behavior }: { behavior: BehaviorFinding }) {
  const conditions = conditionsPassed(behavior);
  const overlap = overlapMinutes(behavior);
  return (
    <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
      {overlap !== null ? (
        <Tooltip title="The rule checks that the metrics changed at the same time, not just in the same run." arrow>
          <Chip size="small" color="success" variant="outlined" label={`Both at the same time · overlapped ${overlap} min`} />
        </Tooltip>
      ) : null}
      {conditions.total ? <Chip size="small" variant="outlined" label={`${conditions.passed} of ${conditions.total} conditions passed`} /> : null}
      <Chip size="small" variant="outlined" label={behavior.occurrence_count > 1 ? `Seen ${behavior.occurrence_count} times` : 'Seen once'} />
    </Stack>
  );
}
