import { Box, Link, Stack, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { ui } from '../standalone/theme';
import { recurrenceForCase } from '../utils/recurringNextStep';

// The same window and grouping the Recurring problems page opens on, so "See the pattern" lands on
// the group this banner counted.
const WINDOW_DAYS = 90;

/** "Seen before" on a case: when the case is one of a problem that keeps coming back, say how often
 * and what was found last time, and link to the pattern. Nothing shows for a one-off case. */
export function CaseRecurrenceBanner({ caseId }: { caseId: number }) {
  const query = useQuery({
    queryKey: ['recurring-problems-membership', WINDOW_DAYS],
    // The banner needs only which group the case is in, not the LLM's group names.
    queryFn: () => api.recurringProblems(WINDOW_DAYS, 3, 'symptom', false),
    retry: false,
    staleTime: 60_000,
  });
  const recurrence = query.data?.available ? recurrenceForCase(query.data.problems, caseId) : null;
  if (!recurrence) return null;
  const { problem, lastCause } = recurrence;

  return (
    <Box
      data-testid="case-recurrence"
      sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap', p: 1.5, border: `1px solid ${ui.yellow}88`, bgcolor: 'var(--os-tint-amber)', borderRadius: '8px' }}
    >
      <Typography sx={{ fontSize: 24, fontWeight: 900, color: ui.yellow, lineHeight: 1 }}>{problem.occurrences}×</Typography>
      <Stack sx={{ flex: 1, minWidth: 220 }}>
        <Typography sx={{ fontWeight: 800 }}>Seen before: this problem happened {problem.occurrences} times in the last {WINDOW_DAYS} days.</Typography>
        <Typography sx={{ color: ui.muted, fontSize: 13 }}>
          {lastCause
            ? <>Found {lastCause.verified ? 'and verified ' : ''}on case #{lastCause.case_id}: {lastCause.root_cause}{lastCause.fix ? <> — fixed by: {lastCause.fix}</> : null}</>
            : 'No cause recorded on the other cases yet.'}
        </Typography>
      </Stack>
      <Link component={RouterLink} to={`/recurring-problems?problem=${problem.central_case_id}`} underline="hover" sx={{ fontWeight: 800, whiteSpace: 'nowrap' }}>
        See the pattern →
      </Link>
    </Box>
  );
}
