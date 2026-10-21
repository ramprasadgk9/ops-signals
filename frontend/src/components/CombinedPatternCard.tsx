import { Box, Button, Card, CardActions, CardContent, Chip, Stack, Tooltip, Typography } from '@mui/material';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { api } from '../api/queries';
import { Pill } from '../standalone/components';
import { ui } from '../standalone/theme';
import type { BehaviorFinding, Finding } from '../types';
import { conditionsPassed, formatChange, overlapMinutes, parseUtc, patternParts } from '../utils/combinedPatterns';
import { useWebPermissions, WEB_LOCK_REASONS } from '../hooks/useWebPermissions';

// Told apart by lightness as well as hue, so the metric dots still read without color.
const PART_COLORS = ['#0d9488', '#d97706', '#7c3aed', '#2563eb'];

type Props = {
  behavior: BehaviorFinding;
  /** The single-metric findings this pattern was made from, when they are in the list. */
  parts?: Finding[];
  onViewFinding?: (finding: Finding) => void;
};

function clock(value: string | null): string | null {
  const time = parseUtc(value);
  return Number.isFinite(time) ? new Date(time).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : null;
}

/** One rule that matched several metrics together, shown with the evidence the engine stored. */
export function CombinedPatternCard({ behavior, parts = [], onViewFinding }: Props) {
  const { canEdit } = useWebPermissions();
  const navigate = useNavigate();
  const createCaseMutation = useMutation({
    mutationFn: () => api.createCaseFromBehavior(behavior.id),
    onSuccess: (data) => navigate(`/cases/${data.case_id}`),
  });
  const metrics = patternParts(behavior);
  const conditions = conditionsPassed(behavior);
  const overlap = overlapMinutes(behavior);
  return (
    <Card id={`combined-pattern-${behavior.id}`} sx={{ border: '2px solid #14b8a6', height: '100%', display: 'flex', flexDirection: 'column' }}>
      <CardContent sx={{ flexGrow: 1 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1} sx={{ mb: 1 }}>
          <Stack spacing={0.5} sx={{ minWidth: 0 }}>
            <Typography variant="caption" sx={{ color: '#0d9488', fontWeight: 800 }}>
              Combined pattern · {metrics.length} metrics
            </Typography>
            <Typography variant="h6">{behavior.title}</Typography>
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
              {[behavior.service, `rule ${behavior.definition_id}`].filter(Boolean).join(' · ')}
            </Typography>
          </Stack>
          <Pill label={behavior.severity} tone="severity" />
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {behavior.ai_explanation ?? behavior.summary}
        </Typography>

        <Stack spacing={0.75} sx={{ mb: 2 }} aria-label="Metrics in this pattern">
          {metrics.map((part, index) => {
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

        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mb: parts.length ? 2 : 0 }}>
          {overlap !== null ? (
            <Tooltip title="The rule checks that the metrics changed at the same time, not just in the same run." arrow>
              <Chip size="small" color="success" variant="outlined" label={`Both at the same time · overlapped ${overlap} min`} />
            </Tooltip>
          ) : null}
          {conditions.total ? <Chip size="small" variant="outlined" label={`${conditions.passed} of ${conditions.total} conditions passed`} /> : null}
          <Chip size="small" variant="outlined" label={behavior.occurrence_count > 1 ? `Seen ${behavior.occurrence_count} times` : 'Seen once'} />
        </Stack>

        {parts.length ? (
          <Box>
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700, display: 'block', mb: 0.75 }}>
              Made from these {parts.length} findings
            </Typography>
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
              {parts.map((finding) => (
                <Chip key={finding.id} size="small" variant="outlined" clickable onClick={() => onViewFinding?.(finding)} label={finding.plain?.headline ?? finding.title} />
              ))}
            </Stack>
          </Box>
        ) : null}
      </CardContent>
      <CardActions sx={{ gap: 1 }}>
        {behavior.case_id ? (
          <Button size="small" variant="outlined" component={RouterLink} to={`/cases/${behavior.case_id}`}>View Case</Button>
        ) : (
          <span>
            <Button
              size="small"
              variant="outlined"
              onClick={() => createCaseMutation.mutate()}
              disabled={createCaseMutation.isPending || !canEdit}
              title={canEdit ? undefined : WEB_LOCK_REASONS.createCase}
            >
              {createCaseMutation.isPending ? 'Creating...' : 'Create Case'}
            </Button>
          </span>
        )}
        <Button size="small" component={RouterLink} to="/behavior-intelligence" sx={{ color: ui.muted }}>
          See the rule
        </Button>
      </CardActions>
    </Card>
  );
}
