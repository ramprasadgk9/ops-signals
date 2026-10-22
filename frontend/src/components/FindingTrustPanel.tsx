import { Box, Button, LinearProgress, Stack, Tooltip, Typography } from '@mui/material';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/queries';
import type { Finding, FindingVerdict } from '../types';
import { answerLine, movedNote, serviceCaption, serviceHeadline, serviceLabel, serviceProgress, serviceRateLeads, testedCaption, testedHeadline, testedTooltip, VERDICTS } from '../utils/findingTrust';
import { useWebPermissions, WEB_LOCK_REASONS } from '../hooks/useWebPermissions';
import { LockNote } from './LockNote';

type Props = {
  finding: Finding;
  /** Only the "Was this real?" answer: for context findings, whose tested rate is no better than chance. */
  answerOnly?: boolean;
};

function Column({ label, headline, caption, value, color, info }: {
  label: string;
  headline: string;
  caption: string;
  value: number | null;
  color: 'success' | 'warning' | 'inherit';
  info?: string;
}) {
  return (
    <Box sx={{ minWidth: 0 }}>
      <Stack direction="row" spacing={0.5} alignItems="center">
        <Typography variant="caption" sx={{ textTransform: 'uppercase', letterSpacing: '.04em', color: 'text.secondary' }}>{label}</Typography>
        {info ? (
          <Tooltip title={info} arrow>
            <InfoOutlinedIcon aria-label={`About ${label.toLowerCase()}`} sx={{ fontSize: 15, color: 'text.secondary', cursor: 'help' }} />
          </Tooltip>
        ) : null}
      </Stack>
      <Typography sx={{ fontSize: 20, fontWeight: 800, lineHeight: 1.3 }}>{headline}</Typography>
      {value !== null ? (
        <LinearProgress variant="determinate" value={Math.round(value * 100)} color={color} sx={{ height: 7, borderRadius: 4, my: 0.75 }} />
      ) : null}
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1.4 }}>{caption}</Typography>
    </Box>
  );
}

/** "On your service" next to "In testing", and the "Was this real?" answer that feeds the first. */
export function FindingTrustPanel({ finding, answerOnly = false }: Props) {
  const { canEdit } = useWebPermissions();
  const queryClient = useQueryClient();
  const answer = useMutation({
    mutationFn: (verdict: FindingVerdict) => api.findingFeedback(finding.id!, verdict),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['findings'] });
      queryClient.invalidateQueries({ queryKey: ['finding-detail'] });
    },
  });
  const trust = finding.trust;
  if (!trust) return null;
  const chosen = answer.variables && answer.isPending ? answer.variables : trust.your_answer;
  const note = movedNote(trust, finding.service);

  return (
    <Box data-testid="finding-trust" sx={{ borderTop: 1, borderColor: 'divider', pt: 1.5, mt: 1.5 }}>
      {note ? <Typography variant="body2" sx={{ fontWeight: 700, mb: 1 }}>{note}</Typography> : null}
      {answerOnly ? null : <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 2 }}>
        <Column
          label={serviceLabel(trust)}
          headline={serviceHeadline(trust)}
          caption={serviceCaption(trust, finding.service)}
          value={serviceProgress(trust)}
          color={serviceRateLeads(trust) ? 'success' : 'inherit'}
        />
        <Column
          label="In testing"
          headline={testedHeadline(trust)}
          caption={testedCaption(trust)}
          value={trust.tested ? trust.tested.real : null}
          color="inherit"
          info={testedTooltip(trust) || undefined}
        />
      </Box>}
      {finding.id ? (
        <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap" sx={{ mt: answerOnly ? 0 : 1.5 }}>
          <Typography variant="caption" color="text.secondary">Was this real?</Typography>
          {VERDICTS.map((verdict) => (
            <Button
              key={verdict.id}
              size="small"
              variant={chosen === verdict.id ? 'contained' : 'outlined'}
              disabled={answer.isPending || !canEdit}
              onClick={() => answer.mutate(verdict.id)}
              aria-pressed={chosen === verdict.id}
              sx={{ textTransform: 'none' }}
            >
              {verdict.label}
            </Button>
          ))}
          {answer.isError ? <Typography variant="caption" color="error">Couldn't save your answer.</Typography> : null}
        </Stack>
      ) : null}
      {finding.id && !canEdit ? <LockNote>{WEB_LOCK_REASONS.answer}</LockNote> : null}
      {answerLine(trust) ? <Typography variant="caption" color="text.secondary" component="p" sx={{ mt: 0.75 }}>{answerLine(trust)}</Typography> : null}
    </Box>
  );
}
