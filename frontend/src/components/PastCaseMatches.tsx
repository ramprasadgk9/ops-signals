import React from 'react';
import { Box, Button, Chip, Link, Stack, Typography } from '@mui/material';
import { CaseOriginBadge } from './CaseOriginBadge';
import { ui } from '../standalone/theme';
import type { PastCaseMatch } from '../types';
import { rankPastMatches } from '../utils/pastCaseMatches';

export { rankPastMatches };

/** Past cases resembling a finding or a case: same-service matches up front, labelled strong or
 * possible; matches on other services folded away and labelled as such. */
export function PastCaseMatches({ matches, service, emptyText }: { matches: PastCaseMatch[]; service?: string | null; emptyText: string }) {
  const [showOthers, setShowOthers] = React.useState(false);
  const ranked = rankPastMatches(matches);
  const sameService = ranked.filter((match) => match.same_service);
  const otherServices = ranked.filter((match) => !match.same_service);

  if (!ranked.length) return <Typography sx={{ color: ui.muted, fontSize: 14 }}>{emptyText}</Typography>;

  return (
    <Stack spacing={1.5}>
      {sameService.length ? (
        <Stack spacing={1}>
          {service ? <Typography sx={{ fontSize: 12, fontWeight: 800, color: ui.muted, textTransform: 'uppercase' }}>On {service}</Typography> : null}
          {sameService.map((match) => <MatchRow key={match.case_id} match={match} />)}
        </Stack>
      ) : (
        <Typography sx={{ color: ui.muted, fontSize: 14 }}>No past cases on {service ?? 'this service'}.</Typography>
      )}
      {otherServices.length ? (
        <Box>
          <Button size="small" onClick={() => setShowOthers(!showOthers)} sx={{ textTransform: 'none', px: 0, fontWeight: 700 }}>
            {showOthers ? 'Hide' : 'Show'} {otherServices.length} {otherServices.length === 1 ? 'match' : 'matches'} on other services
          </Button>
          {showOthers ? (
            <Stack spacing={1} sx={{ mt: 1 }}>
              {otherServices.map((match) => <MatchRow key={match.case_id} match={match} />)}
            </Stack>
          ) : null}
        </Box>
      ) : null}
    </Stack>
  );
}

function MatchRow({ match }: { match: PastCaseMatch }) {
  const [showCopies, setShowCopies] = React.useState(false);
  const strong = match.strength !== 'possible';
  const fix = match.corrective_action || match.outcome_summary;
  const copies = match.more_like_this ?? [];
  return (
    <Box sx={{ p: 1.5, border: `1px solid ${ui.border}`, borderRadius: '8px', bgcolor: strong ? '#fff' : '#fafafa' }} data-testid="past-case-match">
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        <Link href={`/cases/${match.case_id}`} underline="hover" sx={{ fontWeight: 800, color: ui.text }}>
          {match.title}
        </Link>
        <Chip
          size="small"
          label={`${strong ? 'Strong' : 'Possible'} match · ${Math.round(match.similarity_score * 100)}%`}
          color={strong ? 'success' : 'default'}
          variant={strong ? 'filled' : 'outlined'}
        />
        <CaseOriginBadge source={match.source} sourceId={match.source_id} sourceUrl={match.source_url} />
      </Stack>
      <Typography sx={{ fontSize: 12, color: ui.muted, mt: 0.25 }}>
        {[match.service, match.metric_name ?? (match.origin === 'imported' ? 'past incident' : null)].filter(Boolean).join(' · ')}
      </Typography>
      {match.root_cause_summary ? <Typography sx={{ fontSize: 13, mt: 0.75 }}><b>Cause:</b> {match.root_cause_summary}</Typography> : null}
      {fix ? <Typography sx={{ fontSize: 13, mt: 0.25 }}><b>Fix:</b> {fix}</Typography> : null}
      {copies.length ? (
        <Box sx={{ mt: 0.75 }}>
          <Chip
            size="small"
            variant="outlined"
            label={showCopies ? 'Hide repeats' : `+${copies.length} more like this`}
            onClick={() => setShowCopies(!showCopies)}
            sx={{ fontWeight: 700 }}
          />
          {showCopies ? (
            <Stack spacing={0.25} sx={{ mt: 0.75 }}>
              {copies.map((copy) => (
                <Typography key={copy.case_id} sx={{ fontSize: 13 }}>
                  <Link href={`/cases/${copy.case_id}`} underline="hover">{copy.title}</Link>
                  <span style={{ color: ui.muted }}> · {Math.round(copy.similarity_score * 100)}%</span>
                </Typography>
              ))}
            </Stack>
          ) : null}
        </Box>
      ) : null}
    </Box>
  );
}
