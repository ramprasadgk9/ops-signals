import { Box, Button, Card, CardActions, CardContent, Chip, Stack, Typography } from '@mui/material';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { api } from '../api/queries';
import { Pill } from '../standalone/components';
import { ui } from '../standalone/theme';
import type { BehaviorFinding, Finding } from '../types';
import { patternParts } from '../utils/combinedPatterns';
import { PatternMetrics, PatternWhy } from './PatternEvidence';
import { useWebPermissions, WEB_LOCK_REASONS } from '../hooks/useWebPermissions';

type Props = {
  behavior: BehaviorFinding;
  /** The single-metric findings this pattern was made from, when they are in the list. */
  parts?: Finding[];
  onViewFinding?: (finding: Finding) => void;
  /** Opened from a link to this pattern: drawn with a ring so it stands out. */
  highlighted?: boolean;
};

/** One rule that matched several metrics together, shown with the evidence the engine stored. */
export function CombinedPatternCard({ behavior, parts = [], onViewFinding, highlighted = false }: Props) {
  const { canEdit } = useWebPermissions();
  const navigate = useNavigate();
  const createCaseMutation = useMutation({
    mutationFn: () => api.createCaseFromBehavior(behavior.id),
    onSuccess: (data) => navigate(`/cases/${data.case_id}`),
  });
  const metricCount = patternParts(behavior).length;
  return (
    <Card id={`combined-pattern-${behavior.id}`} data-highlighted={highlighted || undefined} sx={{ border: '2px solid #14b8a6', boxShadow: highlighted ? '0 0 0 4px rgba(20, 184, 166, 0.35)' : undefined, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <CardContent sx={{ flexGrow: 1 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1} sx={{ mb: 1 }}>
          <Stack spacing={0.5} sx={{ minWidth: 0 }}>
            <Typography variant="caption" sx={{ color: '#0d9488', fontWeight: 800 }}>
              Combined pattern · {metricCount} metrics
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

        <Box sx={{ mb: 2 }}><PatternMetrics behavior={behavior} /></Box>
        <Box sx={{ mb: parts.length ? 2 : 0 }}><PatternWhy behavior={behavior} /></Box>

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
