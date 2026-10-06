import React from 'react';
import { Box, Button, Chip, CircularProgress, Link, Stack, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { WorkspacePanel } from '../standalone/components';
import { formatDateTime, relativeTime, ui } from '../standalone/theme';
import type { RecurringProblem } from '../types';
import { OCCURRENCE_STATES, OccurrenceTimeline, ProblemRanking, occurrenceState } from './RecurringCharts';

const WINDOWS = [30, 90, 180, 365];
// Causes shown before "Show N more causes": the timeline carries how often; the causes are text to
// read, so only the first two show. Verified ones come first, so a different, unverified cause can
// sit below them - it stays one click away, never cut.
const CAUSES_SHOWN = 2;
// By symptom: what was seen (different causes of it listed per group). By cause: the same root
// cause and fix, across services and symptoms - only cases with a recorded cause take part.
const GROUPINGS: { id: 'symptom' | 'cause'; label: string }[] = [
  { id: 'symptom', label: 'By symptom' },
  { id: 'cause', label: 'By cause' },
];

/** Problems that keep coming back: past cases grouped by how alike they are, with the causes and
 * fixes found each time. A problem seen many times is a candidate for a lasting fix. */
export function RecurringProblemsPanel() {
  const [days, setDays] = React.useState(90);
  const [groupBy, setGroupBy] = React.useState<'symptom' | 'cause'>('symptom');
  const query = useQuery({
    queryKey: ['recurring-problems', days, groupBy],
    queryFn: () => api.recurringProblems(days, 3, groupBy),
    retry: false,
  });
  const data = query.data;

  return (
    <WorkspacePanel sx={{ p: 2.5 }}>
      <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', md: 'center' }} spacing={2} sx={{ mb: 2 }}>
        <Box>
          <Typography variant="h6" sx={{ fontSize: 18, fontWeight: 900 }}>Recurring problems</Typography>
          <Typography sx={{ color: ui.muted, fontSize: 13 }}>
            Past cases that look alike, grouped. A problem that keeps coming back is worth a lasting fix, not another incident.
          </Typography>
        </Box>
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          {GROUPINGS.map((grouping) => (
            <Chip
              key={grouping.id}
              label={grouping.label}
              onClick={() => setGroupBy(grouping.id)}
              color={groupBy === grouping.id ? 'secondary' : 'default'}
              variant={groupBy === grouping.id ? 'filled' : 'outlined'}
              sx={{ fontWeight: 800 }}
            />
          ))}
          {WINDOWS.map((window) => (
            <Chip
              key={window}
              label={`${window} days`}
              onClick={() => setDays(window)}
              color={days === window ? 'primary' : 'default'}
              variant={days === window ? 'filled' : 'outlined'}
              sx={{ fontWeight: 800 }}
            />
          ))}
        </Stack>
      </Stack>

      {query.isLoading ? <CircularProgress size={20} /> : null}
      {query.isError ? <Typography sx={{ color: ui.muted, fontSize: 14 }}>Recurring problems could not be loaded.</Typography> : null}
      {data && !data.available ? <Typography sx={{ color: ui.muted, fontSize: 14 }}>{data.reason}</Typography> : null}
      {data?.available && !data.problems.length ? (
        <Typography sx={{ color: ui.muted, fontSize: 14 }}>
          No problem happened {data.min_occurrences} or more times in the last {data.window_days} days ({data.cases_considered} cases compared).
        </Typography>
      ) : null}
      {data?.available && data.problems.length ? (
        <Stack spacing={1.5}>
          <ProblemRanking
            problems={data.problems}
            days={data.window_days}
            onSelect={(id) => document.getElementById(`recurring-problem-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
          />
          {data.problems.map((problem) => (
            <ProblemCard key={problem.central_case_id} problem={problem} days={data.window_days} />
          ))}
          <Typography sx={{ color: ui.muted, fontSize: 12 }}>
            {data.cases_considered} cases compared{data.sampled ? ' (a sample of them)' : ''}. Every case in a group is at least{' '}
            {Math.round(data.group_similarity * 100)}% like its central case in {data.group_by === 'cause' ? 'cause and fix' : 'symptom'}.
          </Typography>
        </Stack>
      ) : null}
    </WorkspacePanel>
  );
}

function ProblemCard({ problem, days }: { problem: RecurringProblem; days: number }) {
  const [showCases, setShowCases] = React.useState(false);
  const [showAllCauses, setShowAllCauses] = React.useState(false);
  const hiddenCauses = Math.max(problem.causes.length - CAUSES_SHOWN, 0);
  const causes = showAllCauses ? problem.causes : problem.causes.slice(0, CAUSES_SHOWN);
  return (
    <Box id={`recurring-problem-${problem.central_case_id}`} sx={{ p: 1.5, border: `1px solid ${ui.border}`, borderRadius: '8px' }} data-testid="recurring-problem">
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        <Typography sx={{ fontWeight: 900 }}>{problem.name}</Typography>
        <Chip size="small" color="warning" label={`${problem.occurrences} times in ${days} days`} sx={{ fontWeight: 800 }} />
        {problem.named_by === 'ai' ? <Chip size="small" variant="outlined" color="info" label="AI-named" /> : null}
      </Stack>
      <Typography sx={{ fontSize: 12, color: ui.muted, mt: 0.25 }}>
        {[
          problem.services.join(', '),
          problem.last_seen ? `last ${relativeTime(problem.last_seen)}` : null,
          problem.first_seen ? `first ${formatDateTime(problem.first_seen)}` : null,
          `${problem.verified_root_causes} verified ${problem.verified_root_causes === 1 ? 'cause' : 'causes'}`,
          problem.open_cases ? `${problem.open_cases} still open` : null,
        ].filter(Boolean).join(' · ')}
      </Typography>
      <OccurrenceTimeline cases={problem.cases} days={days} />
      {problem.causes.length ? (
        <Stack spacing={0.5} sx={{ mt: 1 }}>
          {causes.map((cause) => (
            <Typography key={cause.case_id} sx={{ fontSize: 13 }}>
              <b>Cause{cause.verified ? ' (verified)' : ''}:</b> {cause.root_cause}
              {cause.fix ? <> — <b>Fix:</b> {cause.fix}</> : null}
            </Typography>
          ))}
          {hiddenCauses ? (
            <Button size="small" onClick={() => setShowAllCauses(!showAllCauses)} sx={{ textTransform: 'none', px: 0, alignSelf: 'flex-start', fontWeight: 700 }}>
              {showAllCauses ? 'Show fewer causes' : `Show ${hiddenCauses} more ${hiddenCauses === 1 ? 'cause' : 'causes'}`}
            </Button>
          ) : null}
        </Stack>
      ) : (
        <Typography sx={{ fontSize: 13, color: ui.muted, mt: 1 }}>No root cause recorded yet for any of these cases.</Typography>
      )}
      <Button size="small" onClick={() => setShowCases(!showCases)} sx={{ textTransform: 'none', px: 0, mt: 0.5, fontWeight: 700 }}>
        {showCases ? 'Hide' : 'Show'} {problem.occurrences} cases
      </Button>
      {showCases ? (
        <Stack spacing={0.25}>
          {problem.cases.map((item) => (
            <Typography key={item.case_id} sx={{ fontSize: 13 }}>
              <Link component={RouterLink} to={`/cases/${item.case_id}`} underline="hover">{item.title}</Link>
              <span style={{ color: ui.muted }}>
                {' · '}
                {[item.service, item.created_at ? formatDateTime(item.created_at) : null, OCCURRENCE_STATES[occurrenceState(item)].label, item.origin === 'imported' ? 'imported' : null]
                  .filter(Boolean)
                  .join(' · ')}
              </span>
            </Typography>
          ))}
        </Stack>
      ) : null}
    </Box>
  );
}
