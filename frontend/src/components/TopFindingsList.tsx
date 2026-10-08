import { Grid2 as Grid } from '@mui/material';
import type { Finding, MetricUsageItem, Signal } from '../types';
import type { FindingGroup } from '../utils/findingSearch';
import { FindingCard } from './FindingCard';

type Props = {
  groups: FindingGroup[];
  signals?: Signal[];
  onViewDetails?: (finding: Finding) => void;
  /** Lists each run of a repeated finding. */
  onShowRuns?: (finding: Finding) => void;
  /** Latest metric usage by metric name, for the "who watches this" tag. */
  usageByMetric?: Record<string, MetricUsageItem>;
};

/** Renders one card per group, in the order given; the caller sorts, filters, groups and pages them. */
export function TopFindingsList({ groups, signals = [], onViewDetails, onShowRuns, usageByMetric }: Props) {
  return (
    <Grid container spacing={2}>
      {groups.map(({ finding, runs, firstSeen, lastSeen }) => (
        <Grid key={finding.id} size={{ xs: 12, md: 6 }}>
          <FindingCard
            finding={finding}
            signals={signals}
            onViewDetails={onViewDetails}
            usage={usageByMetric?.[finding.metric_name]}
            repeats={{ count: runs.length, firstSeen, lastSeen, onShowAll: onShowRuns ? () => onShowRuns(finding) : undefined }}
          />
        </Grid>
      ))}
    </Grid>
  );
}
