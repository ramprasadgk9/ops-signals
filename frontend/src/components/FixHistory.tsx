import React from 'react';
import { Alert, Box, Button, Chip, CircularProgress, Link, Stack, Typography } from '@mui/material';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { ui } from '../standalone/theme';
import type { FixOutcome } from '../types';

const OUTCOME_COLORS: Record<FixOutcome['status'], 'success' | 'warning' | 'default'> = {
  held: 'success',
  came_back: 'warning',
  too_early: 'default',
  not_fixed: 'default',
  unknown: 'default',
};

/** Whether a fix held, inferred from what happened next (backend/app/memory/fix_outcomes.py). */
export function FixOutcomeChip({ outcome }: { outcome: FixOutcome }) {
  return (
    <Chip
      size="small"
      label={outcome.label}
      color={OUTCOME_COLORS[outcome.status]}
      variant={outcome.status === 'held' || outcome.status === 'came_back' ? 'filled' : 'outlined'}
      sx={{ fontWeight: 700 }}
    />
  );
}

const OUTCOME_NOTE = 'A fix "held" when the same problem didn\'t come back on that service within 30 days.';

/** What fixed this finding's look-alikes before, ranked by how often each fix held, with a
 * draft runbook on request. Shown in a finding's Seen before? panel. */
export function SuggestedFixes({ findingId }: { findingId: number }) {
  const query = useQuery({ queryKey: ['suggested-fixes', findingId], queryFn: () => api.suggestedFixes(findingId), retry: false });
  const draft = useMutation({ mutationFn: () => api.runbookDraft(findingId) });
  const fixes = query.data?.fixes ?? [];
  if (!query.data?.available || !fixes.length) return null;

  return (
    <Box sx={{ mb: 2, p: 1.5, border: `1px solid ${ui.border}`, borderRadius: '8px' }} data-testid="suggested-fixes">
      <Typography sx={{ fontWeight: 800 }}>What fixed this before</Typography>
      <Typography sx={{ fontSize: 12, color: ui.muted, mb: 1 }}>{OUTCOME_NOTE}</Typography>
      <Stack spacing={1}>
        {fixes.map((fix) => (
          <Box key={fix.sources.map((source) => source.case_id).join('-')}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <Typography sx={{ fontSize: 14, fontWeight: 700 }}>{fix.fix}</Typography>
              <Chip size="small" label={fix.label} color={fix.held ? 'success' : fix.came_back ? 'warning' : 'default'} variant="outlined" sx={{ fontWeight: 700 }} />
            </Stack>
            {fix.root_cause ? <Typography sx={{ fontSize: 13, color: ui.muted }}>Cause: {fix.root_cause}</Typography> : null}
            <Typography sx={{ fontSize: 12, color: ui.muted }}>
              From{' '}
              {fix.sources.map((source, index) => (
                <React.Fragment key={source.case_id}>
                  {index ? ', ' : ''}
                  <Link href={`/cases/${source.case_id}`} underline="hover">#{source.case_id}</Link> ({source.outcome.label.toLowerCase()})
                </React.Fragment>
              ))}
            </Typography>
          </Box>
        ))}
      </Stack>
      <Button size="small" variant="outlined" onClick={() => draft.mutate()} disabled={draft.isPending} sx={{ mt: 1.5, textTransform: 'none', fontWeight: 700 }}>
        {draft.isPending ? 'Drafting…' : 'Draft a runbook'}
      </Button>
      {draft.data && !draft.data.available ? <Typography sx={{ fontSize: 13, color: ui.muted, mt: 1 }}>{draft.data.reason}</Typography> : null}
      {draft.isError ? <Typography sx={{ fontSize: 13, color: ui.muted, mt: 1 }}>The runbook draft could not be made.</Typography> : null}
      {draft.data?.available && draft.data.draft ? (
        <Alert severity="info" sx={{ mt: 1, whiteSpace: 'pre-wrap' }} data-testid="runbook-draft">
          <Typography sx={{ fontSize: 12, fontWeight: 800, mb: 0.5 }}>Draft from past fixes — check it before using. Not saved.</Typography>
          {draft.data.draft}
        </Alert>
      ) : null}
    </Box>
  );
}

/** Other cases this case's cause and fix also resolved, on any service, with how each fix held.
 * Shown on a case's Similar Cases tab. */
export function SameFixElsewhere({ caseId }: { caseId: number }) {
  const query = useQuery({ queryKey: ['same-fix', caseId], queryFn: () => api.sameFix(caseId), retry: false });
  if (query.isLoading) return <CircularProgress size={20} />;
  const data = query.data;
  if (!data) return null;

  return (
    <Box data-testid="same-fix">
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mb: 0.5 }}>
        <Typography sx={{ fontWeight: 800 }}>Same fix elsewhere</Typography>
        {data.outcome && data.outcome.status !== 'not_fixed' ? (
          <>
            <Typography sx={{ fontSize: 13, color: ui.muted }}>This case's fix:</Typography>
            <FixOutcomeChip outcome={data.outcome} />
          </>
        ) : null}
      </Stack>
      <Typography sx={{ fontSize: 12, color: ui.muted, mb: 1 }}>Past cases with the same cause and fix, on any service. {OUTCOME_NOTE}</Typography>
      {!data.available ? <Typography sx={{ fontSize: 14, color: ui.muted }}>{data.reason}</Typography> : null}
      {data.available && !data.matches.length ? (
        <Typography sx={{ fontSize: 14, color: ui.muted }}>No other case was fixed this way.</Typography>
      ) : null}
      <Stack spacing={1}>
        {data.matches.map((match) => (
          <Box key={match.case_id} sx={{ p: 1.25, border: `1px solid ${ui.border}`, borderRadius: '8px' }}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <Link href={`/cases/${match.case_id}`} underline="hover" sx={{ fontWeight: 800, color: ui.text }}>{match.title}</Link>
              <FixOutcomeChip outcome={match.outcome} />
            </Stack>
            <Typography sx={{ fontSize: 12, color: ui.muted }}>
              {[match.service, `${Math.round(match.similarity_score * 100)}% same cause and fix`, match.rca_verified ? 'verified cause' : 'root cause unconfirmed'].filter(Boolean).join(' · ')}
            </Typography>
            {match.corrective_action ? <Typography sx={{ fontSize: 13, mt: 0.25 }}><b>Fix:</b> {match.corrective_action}</Typography> : null}
          </Box>
        ))}
      </Stack>
    </Box>
  );
}
