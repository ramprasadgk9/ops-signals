import { Grid2 as Grid } from '@mui/material';
import type { BehaviorFinding, Finding, MetricUsageItem, Signal } from '../types';
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
  /** Combined patterns by finding id, for the "Part of" tag. */
  patternsByFinding?: Map<number, BehaviorFinding[]>;
};

/** The patterns any run in a group belongs to, once each. */
function groupPatterns(runs: Finding[], patternsByFinding?: Map<number, BehaviorFinding[]>): BehaviorFinding[] {
  const seen = new Map<number, BehaviorFinding>();
  for (const run of runs) {
    for (const behavior of (run.id != null && patternsByFinding?.get(run.id)) || []) seen.set(behavior.id, behavior);
  }
  return [...seen.values()];
}

/** Renders one card per group, in the order given; the caller sorts, filters, groups and pages them. */
export function TopFindingsList({ groups, signals = [], onViewDetails, onShowRuns, usageByMetric, patternsByFinding }: Props) {
  return (
    <Grid container spacing={2}>
      {groups.map(({ finding, runs, firstSeen, lastSeen, latest, startedAt }) => (
        <Grid key={finding.id} size={{ xs: 12, md: 6 }}>
          <FindingCard
            finding={finding}
            signals={signals}
            onViewDetails={onViewDetails}
            usage={usageByMetric?.[finding.metric_name]}
            partOf={groupPatterns(runs, patternsByFinding)}
            repeats={{ count: runs.length, firstSeen, lastSeen, latest, startedAt, onShowAll: onShowRuns ? () => onShowRuns(finding) : undefined }}
          />
        </Grid>
      ))}
    </Grid>
  );
}
