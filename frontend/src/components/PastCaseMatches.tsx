import React from 'react';
import { Box, Button, Chip, Link, Stack, Tooltip, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import { CaseOriginBadge } from './CaseOriginBadge';
import { ui } from '../standalone/theme';
import type { PastCaseMatch } from '../types';
import { fixedCountSentence, matchDate, matchOutcome, matchStatus, rankPastMatches } from '../utils/pastCaseMatches';

const TWO_LINES = { display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' } as const;
const STATUS_COLOR = { resolved: 'success.main', progress: 'info.main', open: 'warning.main' } as const;

export { rankPastMatches };

/** Past cases resembling a finding or a case: same-service matches up front, labelled strong or
 * possible; matches on other services folded away and labelled as such. */
export function PastCaseMatches({ matches, service, emptyText }: { matches: PastCaseMatch[]; service?: string | null; emptyText: string }) {
  const [showOthers, setShowOthers] = React.useState(false);
  const ranked = rankPastMatches(matches);
  const sameService = ranked.filter((match) => match.same_service);
  const otherServices = ranked.filter((match) => !match.same_service);

  if (!ranked.length) return <Typography sx={{ color: ui.muted, fontSize: 14 }}>{emptyText}</Typography>;

  const fixed = fixedCountSentence(ranked);
  return (
    <Stack spacing={1.5}>
      {fixed ? <Typography sx={{ fontSize: 14, fontWeight: 700 }} data-testid="past-case-fixed-count">{fixed}</Typography> : null}
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
  const copies = match.more_like_this ?? [];
  const outcome = matchOutcome(match);
  const status = matchStatus(match);
  const fullOutcome = outcome.parts.map((part) => `${part.label}${part.unconfirmed ? ' (unconfirmed)' : ''}: ${part.text}`).join(' ');
  return (
    <Box sx={{ p: 1.5, border: `1px solid ${ui.border}`, borderRadius: '8px', bgcolor: strong ? 'var(--os-surface)' : 'var(--os-surface-alt)' }} data-testid="past-case-match">
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        <Link component={RouterLink} to={`/cases/${match.case_id}`} underline="hover" sx={{ fontWeight: 800, color: ui.text }}>
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
        {[match.service, match.metric_name ?? (match.origin === 'imported' ? 'past incident' : null), matchDate(match.opened_at)].filter(Boolean).join(' · ')}
      </Typography>
      {outcome.parts.length ? (
        <Tooltip title={fullOutcome} placement="bottom-start">
          <Typography sx={{ ...TWO_LINES, fontSize: 13, mt: 0.75 }} data-testid="past-case-outcome">
            {outcome.parts.map((part, index) => (
              <React.Fragment key={part.label}>
                {index ? ' ' : ''}
                <b>{part.label}</b>
                {part.unconfirmed ? <Typography component="span" sx={{ fontSize: 13, color: 'warning.main', fontWeight: 700 }}> (unconfirmed)</Typography> : null}
                : {part.text}
              </React.Fragment>
            ))}
          </Typography>
        </Tooltip>
      ) : (
        <Typography sx={{ fontSize: 13, mt: 0.75, color: ui.muted }} data-testid="past-case-outcome">{outcome.empty}</Typography>
      )}
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
                  <Link component={RouterLink} to={`/cases/${copy.case_id}`} underline="hover">{copy.title}</Link>
                  <span style={{ color: ui.muted }}> · Case #{copy.case_id} · {Math.round(copy.similarity_score * 100)}%</span>
                </Typography>
              ))}
            </Stack>
          ) : null}
        </Box>
      ) : null}
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mt: 1, pt: 0.75, borderTop: `1px solid ${ui.border}` }}>
        <Typography sx={{ fontSize: 13 }} data-testid="past-case-status">
          <Box component="span" sx={{ fontWeight: 700, color: STATUS_COLOR[status.tone] }}>{status.label}</Box>
          {status.detail ? <Box component="span" sx={{ color: ui.muted }}> · {status.detail}</Box> : null}
        </Typography>
        <Link component={RouterLink} to={`/cases/${match.case_id}`} underline="hover" sx={{ fontSize: 13, fontWeight: 700 }}>
          Case #{match.case_id} · Open case →
        </Link>
      </Stack>
    </Box>
  );
}
