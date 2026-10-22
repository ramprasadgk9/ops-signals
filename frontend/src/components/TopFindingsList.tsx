import { Grid2 as Grid } from '@mui/material';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/queries';
import type { BehaviorFinding, Finding, FindingDetailsSection, MetricUsageItem, SeenBeforeResponse } from '../types';
import type { FindingGroup } from '../utils/findingSearch';
import { FindingCard } from './FindingCard';

type Props = {
  groups: FindingGroup[];
  onViewDetails?: (finding: Finding, section?: FindingDetailsSection) => void;
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
export function TopFindingsList({ groups, onViewDetails, onShowRuns, usageByMetric, patternsByFinding }: Props) {
  const queryClient = useQueryClient();
  const ids = groups.map(({ finding }) => finding.id).filter((id): id is number => typeof id === 'number');
  // Seen before? for the whole page in one request; each answer also fills the details drawer's cache.
  const seenBeforeQuery = useQuery({
    queryKey: ['findings-seen-before', ids],
    queryFn: async () => {
      const answers = await api.findingsSeenBefore(ids);
      for (const answer of answers) queryClient.setQueryData(['finding-seen-before', answer.finding_id], answer);
      return new Map<number, SeenBeforeResponse>(answers.map((answer) => [answer.finding_id, answer]));
    },
    enabled: ids.length > 0,
    retry: false,
    staleTime: 60_000,
  });
  return (
    <Grid container spacing={2}>
      {groups.map(({ finding, runs, firstSeen, lastSeen, latest, startedAt }) => (
        <Grid key={finding.id} size={{ xs: 12, md: 6 }}>
          <FindingCard
            finding={finding}
            onViewDetails={onViewDetails}
            usage={usageByMetric?.[finding.metric_name]}
            partOf={groupPatterns(runs, patternsByFinding)}
            seenBefore={finding.id != null ? seenBeforeQuery.data?.get(finding.id) : undefined}
            repeats={{ count: runs.length, firstSeen, lastSeen, latest, startedAt, onShowAll: onShowRuns ? () => onShowRuns(finding) : undefined }}
          />
        </Grid>
      ))}
    </Grid>
  );
}
