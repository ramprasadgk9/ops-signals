import { Box, Button, Grid2 as Grid, Stack, Tooltip, Typography } from '@mui/material';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import { WorkspacePanel } from '../standalone/components';
import { formatDateTime, ui } from '../standalone/theme';
import type { MetricUsageCost, MetricUsageItem, MetricUsageSnapshot } from '../types';
import { METRIC_USAGE_STATUSES } from '../utils/metricUsage';

const COST_SETTING = 'OPS_SIGNALS_METRIC_USAGE_COST_PER_1K_SERIES';

export function formatMoney(amount: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency, maximumFractionDigits: amount >= 100 ? 0 : 2 }).format(amount);
  } catch {
    return `${amount.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${currency}`; // not an ISO currency code
  }
}

function percent(part: number, whole: number): string {
  return whole ? `${Math.round((100 * part) / whole)}%` : '0%';
}

type Props = {
  snapshot: MetricUsageSnapshot;
  cost: MetricUsageCost | null;
  blindSpots: MetricUsageItem[];
  /** Completed checks, newest first. */
  history: MetricUsageSnapshot[];
  /** Opens the not-watched metrics, where each can be added to Grafana or dropped. */
  onReviewUnused?: () => void;
};

/** What the check is worth, for whoever doesn't read metric names: unused storage (as money when
 * the operator set a rate), problems nobody would have seen, and whether coverage is improving.
 * Every figure says how it was worked out. */
export function MetricUsageValuePanel({ snapshot, cost, blindSpots, history, onReviewUnused }: Props) {
  const problems = blindSpots.reduce((sum, item) => sum + item.problem_findings, 0);
  return (
    <Grid container spacing={1.5} data-testid="metric-usage-value">
      <Grid size={{ xs: 12, md: 4 }}><UnusedStorageTile snapshot={snapshot} cost={cost} onReview={onReviewUnused} /></Grid>
      <Grid size={{ xs: 12, md: 4 }}>
        <ValueTile
          testId="value-unseen"
          headline={`${problems} ${problems === 1 ? 'problem' : 'problems'}`}
          headlineColor={problems ? METRIC_USAGE_STATUSES.blind_spot.color : ui.text}
          label="nobody would have seen"
          detail={blindSpots.length
            ? `On ${blindSpots.length} ${blindSpots.length === 1 ? 'metric' : 'metrics'} with no dashboard or alert, in the last 24 hours.`
            : 'Every metric with a recent problem is on a dashboard or in an alert.'}
          how="Significant or critical findings in the last 24 hours on metrics that no Grafana dashboard panel or alert rule reads. Ops Signals flagged them; nothing else would have."
        />
      </Grid>
      <Grid size={{ xs: 12, md: 4 }}><TrendTile history={history} /></Grid>
    </Grid>
  );
}

function UnusedStorageTile({ snapshot, cost, onReview }: { snapshot: MetricUsageSnapshot; cost: MetricUsageCost | null; onReview?: () => void }) {
  const { series_unwatched: unused, series_total: total } = snapshot;
  if (unused === null || total === null) {
    return (
      <ValueTile
        testId="value-storage"
        headline="—"
        label="unused storage"
        detail="Series couldn't be counted on this backend; see the warnings at the bottom of the page."
        how="Counted with one query per connection: count by (__name__, job) of every active series. Some backends refuse it above their query limits."
      />
    );
  }
  // Series lead: they're exact. Money is an estimate, only as good as the rate the operator set.
  const priced = cost && cost.unwatched_monthly !== null ? cost : null;
  return (
    <ValueTile
      testId="value-storage"
      headline={`${unused.toLocaleString()} series`}
      label="on metrics no dashboard or alert uses"
      detail={`${percent(unused, total)} of all ${total.toLocaleString()}. Some may still matter: add those to Grafana, drop the rest.`}
      note={priced ? `About ${formatMoney(priced.unwatched_monthly!, priced.currency)} / month at your rate` : undefined}
      action={onReview ? { label: 'See these metrics →', onClick: onReview } : undefined}
      how={priced
        ? `Active series in metrics that no dashboard panel or alert reads (blind spots and not-watched metrics), summed over all connections. Cost: ${unused.toLocaleString()} series ÷ 1,000 × ${formatMoney(priced.per_1k_series_month, priced.currency)} per 1,000 series per month (the rate set in ${COST_SETTING}); all series: ${formatMoney(priced.total_monthly ?? 0, priced.currency)} / month.`
        : `Active series in metrics that no dashboard panel or alert reads (blind spots and not-watched metrics), summed over all connections. Set ${COST_SETTING} to also see an estimated monthly cost.`}
    />
  );
}

function TrendTile({ history }: { history: MetricUsageSnapshot[] }) {
  const completed = history.filter((item) => item.status === 'completed');
  if (completed.length < 2) {
    return (
      <ValueTile
        testId="value-trend"
        headline="Trend"
        label="after the next check"
        detail="Each check is kept, so the change in coverage and blind spots shows from the second one on."
        how="Compares the oldest kept check with the latest one."
      />
    );
  }
  const latest = completed[0];
  const oldest = completed[completed.length - 1];
  const fewerBlind = latest.blind_spots < oldest.blind_spots;
  return (
    <ValueTile
      testId="value-trend"
      headline={`${oldest.watched_percent ?? 0}% → ${latest.watched_percent ?? 0}%`}
      headlineColor={(latest.watched_percent ?? 0) > (oldest.watched_percent ?? 0) ? METRIC_USAGE_STATUSES.watched.color : ui.text}
      label="of metrics watched"
      detail={`Blind spots ${oldest.blind_spots} → ${latest.blind_spots}${fewerBlind ? ' ✓' : ''} · since ${formatDateTime(oldest.created_at)}`}
      how={`The oldest kept check (${formatDateTime(oldest.created_at)}) against the latest (${formatDateTime(latest.created_at)}), out of ${completed.length} checks.`}
    />
  );
}

function ValueTile({ testId, headline, headlineColor = ui.text, label, detail, note, how, action }: {
  testId: string; headline: string; headlineColor?: string; label: string; detail: string; note?: string; how: string;
  action?: { label: string; onClick: () => void };
}) {
  return (
    <WorkspacePanel sx={{ p: 2, height: '100%' }}>
      <Box data-testid={testId}>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
          <Typography sx={{ fontSize: 26, fontWeight: 800, lineHeight: 1.15, color: headlineColor, overflowWrap: 'anywhere' }}>{headline}</Typography>
          <Tooltip title={how} arrow>
            <InfoOutlinedIcon aria-label={`How this is worked out: ${how}`} sx={{ fontSize: 18, color: ui.muted, mt: 0.5, cursor: 'help', flexShrink: 0 }} />
          </Tooltip>
        </Stack>
        <Typography sx={{ fontSize: 14, fontWeight: 700, color: ui.text }}>{label}</Typography>
        <Typography sx={{ fontSize: 12.5, color: ui.muted, mt: 0.5 }}>{detail}</Typography>
        {note ? <Typography sx={{ fontSize: 12.5, color: ui.text, mt: 0.5 }}>{note}</Typography> : null}
        {action ? (
          <Button size="small" onClick={action.onClick} sx={{ textTransform: 'none', fontWeight: 700, px: 0, mt: 0.5 }}>{action.label}</Button>
        ) : null}
      </Box>
    </WorkspacePanel>
  );
}
