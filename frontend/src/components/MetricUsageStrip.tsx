import { Box, Button, Stack, Typography } from '@mui/material';
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded';
import { Link as RouterLink } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { WorkspacePanel } from '../standalone/components';
import { ui } from '../standalone/theme';
import { METRIC_USAGE_STATUSES } from '../utils/metricUsage';

const NAMED = 3;

/** One line on the Overview when the latest metric usage check found blind spots; nothing otherwise. */
export function MetricUsageStrip() {
  const query = useQuery({ queryKey: ['metric-usage-blind-spots'], queryFn: () => api.metricUsage(['blind_spot'], NAMED), retry: false });
  const snapshot = query.data?.snapshot;
  if (!snapshot || snapshot.blind_spots === 0) return null;
  const names = (query.data?.items ?? []).map((item) => item.metric);
  const more = snapshot.blind_spots - names.length;
  return (
    <WorkspacePanel sx={{ p: 2, borderColor: METRIC_USAGE_STATUSES.blind_spot.color, bgcolor: '#fff5f5' }}>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} alignItems={{ xs: 'flex-start', md: 'center' }} justifyContent="space-between" data-testid="metric-usage-strip">
        <Stack direction="row" spacing={1.25} alignItems="flex-start">
          <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: METRIC_USAGE_STATUSES.blind_spot.color, mt: 0.75, flexShrink: 0 }} />
          <Box>
            <Typography sx={{ fontWeight: 800, color: ui.text }}>
              {snapshot.blind_spots} {snapshot.blind_spots === 1 ? 'metric had problems' : 'metrics had problems'} that no dashboard or alert shows
            </Typography>
            <Typography sx={{ fontSize: 13, color: ui.muted, overflowWrap: 'anywhere' }}>
              {names.join(', ')}{more > 0 ? ` and ${more} more` : ''} · {snapshot.watched} of {snapshot.metrics_total} metrics are watched
            </Typography>
          </Box>
        </Stack>
        <Button component={RouterLink} to="/metric-usage" endIcon={<ArrowForwardRoundedIcon />} sx={{ textTransform: 'none', fontWeight: 800, flexShrink: 0 }}>
          Open Metric Usage
        </Button>
      </Stack>
    </WorkspacePanel>
  );
}
