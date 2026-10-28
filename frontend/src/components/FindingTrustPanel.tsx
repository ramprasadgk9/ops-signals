import { Box, Button, LinearProgress, Link, Stack, Typography } from '@mui/material';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/queries';
import type { Finding, FindingDetailsSection, FindingVerdict, SeenBeforeResponse } from '../types';
import { ui } from '../standalone/theme';
import { afterDays } from '../utils/fixCameBack';
import { answerLine, movedNote, serviceCaption, serviceHeadline, serviceLabel, serviceProgress, serviceRateLeads, VERDICTS } from '../utils/findingTrust';
import { useWebPermissions, WEB_LOCK_REASONS } from '../hooks/useWebPermissions';
import { LockNote } from './LockNote';

type Props = {
  finding: Finding;
  /** Only the "Was this real?" answer: for context findings, whose tested rate is no better than chance. */
  answerOnly?: boolean;
  /** Past cases like this finding; the column shows only when past cases can be searched. */
  seenBefore?: SeenBeforeResponse;
  /** Opens the finding's details at its past cases, or at the "came back after a fix" banner. */
  onSeePastCases?: (section?: FindingDetailsSection) => void;
};

function Column({ label, headline, caption, value, color }: {
  label: string;
  headline: string;
  caption: string;
  value: number | null;
  color: 'success' | 'inherit';
}) {
  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography variant="caption" sx={{ textTransform: 'uppercase', letterSpacing: '.04em', color: 'text.secondary' }}>{label}</Typography>
      <Typography sx={{ fontSize: 20, fontWeight: 800, lineHeight: 1.3 }}>{headline}</Typography>
      {value !== null ? (
        <LinearProgress variant="determinate" value={Math.round(value * 100)} color={color} sx={{ height: 7, borderRadius: 4, my: 0.75 }} />
      ) : null}
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1.4 }}>{caption}</Typography>
    </Box>
  );
}

function SeenBeforeColumn({ seenBefore, onSeePastCases }: { seenBefore: SeenBeforeResponse; onSeePastCases?: (section?: FindingDetailsSection) => void }) {
  const closest = seenBefore.matches[0];
  const cameBack = seenBefore.came_back;
  if (cameBack) {
    return (
      <Box sx={{ minWidth: 0 }} data-testid="finding-seen-before">
        <Typography variant="caption" sx={{ textTransform: 'uppercase', letterSpacing: '.04em', color: 'text.secondary' }}>Seen before</Typography>
        <Typography sx={{ fontSize: 20, fontWeight: 800, lineHeight: 1.3, color: ui.yellow }}>↻ Fix didn't hold</Typography>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1.4, mt: 0.75 }}>
          Came back {afterDays(cameBack.days)} after case #{cameBack.case_id} was fixed.
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1.4 }}>Fix then: {cameBack.fix}</Typography>
        {onSeePastCases ? (
          <Link component="button" type="button" variant="caption" onClick={() => onSeePastCases('came-back')} sx={{ fontWeight: 700, mt: 0.5 }}>
            See what came back
          </Link>
        ) : null}
      </Box>
    );
  }
  return (
    <Box sx={{ minWidth: 0 }} data-testid="finding-seen-before">
      <Typography variant="caption" sx={{ textTransform: 'uppercase', letterSpacing: '.04em', color: 'text.secondary' }}>Seen before</Typography>
      <Typography sx={{ fontSize: 20, fontWeight: 800, lineHeight: 1.3 }}>{seenBefore.novelty?.label ?? (closest ? 'Seen before' : 'New pattern')}</Typography>
      {closest ? (
        <>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1.4, mt: 0.75 }}>
            Closest: “{closest.title}”
          </Typography>
          {closest.corrective_action ? (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1.4 }}>Fixed by: {closest.corrective_action}</Typography>
          ) : null}
          {onSeePastCases ? (
            <Link component="button" type="button" variant="caption" onClick={() => onSeePastCases()} sx={{ fontWeight: 700, mt: 0.5 }}>
              See past cases
            </Link>
          ) : null}
        </>
      ) : (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1.4, mt: 0.75 }}>No past cases look like this yet.</Typography>
      )}
    </Box>
  );
}

/** "On your service" next to "Seen before", and the "Was this real?" answer that feeds the first. The
 * tested rate is on the evidence badge and in the finding's details. */
export function FindingTrustPanel({ finding, answerOnly = false, seenBefore, onSeePastCases }: Props) {
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
  const past = seenBefore?.available ? seenBefore : null;

  return (
    <Box data-testid="finding-trust" sx={{ borderTop: 1, borderColor: 'divider', pt: 1.5, mt: 1.5 }}>
      {note ? <Typography variant="body2" sx={{ fontWeight: 700, mb: 1 }}>{note}</Typography> : null}
      {answerOnly && !past ? null : (
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: answerOnly || !past ? '1fr' : '1fr 1fr' }, gap: 2 }}>
          {answerOnly ? null : (
            <Column
              label={serviceLabel(trust)}
              headline={serviceHeadline(trust)}
              caption={serviceCaption(trust, finding.service)}
              value={serviceProgress(trust)}
              color={serviceRateLeads(trust) ? 'success' : 'inherit'}
            />
          )}
          {past ? <SeenBeforeColumn seenBefore={past} onSeePastCases={onSeePastCases} /> : null}
        </Box>
      )}
      {finding.id ? (
        <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap" sx={{ mt: answerOnly && !past ? 0 : 1.5 }}>
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
