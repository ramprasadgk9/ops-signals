import type { ReactNode } from 'react';
import { Box, Button, Chip, CircularProgress, Link, Stack, Tooltip, Typography } from '@mui/material';
import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { ui } from '../standalone/theme';
import { useAiActive } from './CaseAiDraft';
import type { CameBackAfterFix, FixCameBackWhy, FixOutcome } from '../types';
import { CAME_BACK_RULE, cameBackHeadline, daysBadge, didNotHoldHeadline, fixedOn, whyUnavailable } from '../utils/fixCameBack';

const BANNER_SX = { p: 1.5, border: `1px solid ${ui.yellow}88`, bgcolor: 'var(--os-tint-amber)', borderRadius: '8px' };
const LINK_SX = { fontWeight: 800, whiteSpace: 'nowrap' };

type BannerProps = {
  cameBack: CameBackAfterFix;
  /** On a case the old case is named in the headline; on a finding it gets its own line. */
  onCase?: boolean;
  /** Asks the AI for possible reasons; the button shows only when AI is on. */
  why: () => Promise<FixCameBackWhy>;
  /** Extra line under the fix, e.g. how often the problem happened. */
  note?: ReactNode;
  /** Extra links next to "Open case #N". */
  links?: ReactNode;
  id?: string;
};

/** "This came back N days after it was fixed": a finding or case back soon after a past case on
 * its service was fixed (backend/app/memory/fix_came_back.py). */
export function FixCameBackBanner({ cameBack, onCase = false, why, note, links, id }: BannerProps) {
  const badge = daysBadge(cameBack.days);
  return (
    <Box id={id} data-testid="fix-came-back" sx={{ ...BANNER_SX, scrollMarginTop: 16 }}>
      <Stack direction="row" spacing={2} alignItems="flex-start">
        <Box sx={{ textAlign: 'center', minWidth: 44 }}>
          <Typography sx={{ fontSize: 24, fontWeight: 900, color: ui.yellow, lineHeight: 1 }}>{badge.value}</Typography>
          <Typography sx={{ fontSize: 11, fontWeight: 700, color: ui.yellow }}>{badge.unit}</Typography>
        </Box>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography sx={{ fontWeight: 800 }}>{cameBackHeadline(cameBack, onCase)}</Typography>
          {onCase ? null : (
            <Typography variant="body2">
              Case{' '}
              <Link href={`/cases/${cameBack.case_id}`} underline="hover" sx={{ fontWeight: 700 }}>
                #{cameBack.case_id} {cameBack.title}
              </Link>{' '}
              was resolved on {fixedOn(cameBack.fixed_at)}.
            </Typography>
          )}
          <Typography variant="body2"><b>Fix then:</b> {cameBack.fix}</Typography>
          {cameBack.still_open ? (
            <Typography variant="body2" sx={{ color: ui.muted }}>Still open on that case: {cameBack.still_open}</Typography>
          ) : null}
          {note ? <Typography variant="body2" sx={{ color: ui.muted }}>{note}</Typography> : null}
          <Typography variant="caption" sx={{ color: ui.muted, display: 'block', mt: 0.5 }}>{CAME_BACK_RULE}</Typography>
        </Box>
      </Stack>
      <Stack direction="row" spacing={2} alignItems="center" useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
        <Link href={`/cases/${cameBack.case_id}`} underline="hover" sx={LINK_SX}>Open case #{cameBack.case_id} →</Link>
        {links}
        <WhyButton why={why} />
      </Stack>
    </Box>
  );
}

function WhyButton({ why }: { why: () => Promise<FixCameBackWhy> }) {
  const aiActive = useAiActive();
  const mutation = useMutation({ mutationFn: why });
  if (!aiActive) return null;
  const result = mutation.isError ? ({ available: false, reasons: [], reason_code: 'failed' } as FixCameBackWhy) : mutation.data;
  return (
    <>
      <Button
        size="small"
        variant="outlined"
        color="secondary"
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending || Boolean(result?.available)}
        startIcon={mutation.isPending ? <CircularProgress size={14} color="inherit" /> : <AutoAwesomeRoundedIcon fontSize="small" />}
        sx={{ textTransform: 'none' }}
      >
        {mutation.isPending ? 'Comparing…' : 'Why might it not have held?'}
      </Button>
      {result ? <Box sx={{ flexBasis: '100%' }}><WhyAnswer result={result} /></Box> : null}
    </>
  );
}

function WhyAnswer({ result }: { result: FixCameBackWhy }) {
  if (!result.available) {
    return <Typography variant="body2" sx={{ color: ui.muted }} data-testid="fix-came-back-why">{whyUnavailable(result.reason_code)}</Typography>;
  }
  return (
    <Box data-testid="fix-came-back-why" sx={{ border: 1, borderColor: 'secondary.light', borderRadius: 1, px: 1.5, py: 1, bgcolor: 'action.hover' }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1}>
        <Typography variant="body2" sx={{ fontWeight: 700 }}>Possible reasons</Typography>
        <Chip size="small" color="secondary" variant="outlined" label="AI · not saved" />
      </Stack>
      <Box component="ul" sx={{ m: 0, mt: 0.5, pl: 2.5 }}>
        {result.reasons.map((reason) => <li key={reason}><Typography variant="body2">{reason}</Typography></li>)}
      </Box>
      <Tooltip title={(result.sources ?? []).map((source) => source.label).join(' · ')} arrow>
        <Typography variant="caption" color="text.secondary">Written from the past case and this problem only. Check before acting.</Typography>
      </Tooltip>
    </Box>
  );
}

/** On the old case: its fix came back in a later case. The case stays resolved. */
export function FixDidNotHoldBanner({ outcome, note, links }: { outcome: FixOutcome; note?: ReactNode; links?: ReactNode }) {
  const headline = didNotHoldHeadline(outcome);
  if (!headline) return null;
  return (
    <Box data-testid="fix-did-not-hold" sx={{ ...BANNER_SX, display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
      <Typography sx={{ fontSize: 24, fontWeight: 900, color: ui.yellow, lineHeight: 1 }} aria-hidden>↻</Typography>
      <Stack sx={{ flex: 1, minWidth: 220 }}>
        <Typography sx={{ fontWeight: 800 }}>{headline}</Typography>
        <Typography sx={{ color: ui.muted, fontSize: 13 }}>Worth recording a lasting fix on the new case.</Typography>
        {note ? <Typography sx={{ color: ui.muted, fontSize: 13 }}>{note}</Typography> : null}
      </Stack>
      <Stack direction="row" spacing={2} useFlexGap flexWrap="wrap">
        <Link href={`/cases/${outcome.came_back_case_id}`} underline="hover" sx={LINK_SX}>Open case #{outcome.came_back_case_id} →</Link>
        {links}
      </Stack>
    </Box>
  );
}

/** Both directions for a case; shared by the banner and the header chip (one request). */
export function useCaseFixCameBack(caseId: number) {
  const query = useQuery({ queryKey: ['case-fix-came-back', caseId], queryFn: () => api.caseFixCameBack(caseId), retry: false, staleTime: 60_000 });
  return query.data?.available ? query.data : null;
}

/** "Fix didn't hold" next to the old case's status. */
export function FixDidNotHoldChip({ caseId }: { caseId: number }) {
  const fix = useCaseFixCameBack(caseId);
  if (!fix?.fix_outcome || !didNotHoldHeadline(fix.fix_outcome)) return null;
  return <Chip label="Fix didn't hold" size="small" color="warning" data-testid="fix-did-not-hold-chip" sx={{ fontWeight: 700 }} />;
}
