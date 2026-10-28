import { useState } from 'react';
import { Alert, Box, Button, Chip, CircularProgress, Stack, ToggleButton, ToggleButtonGroup, Tooltip, Typography } from '@mui/material';
import SwapHorizRoundedIcon from '@mui/icons-material/SwapHorizRounded';
import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded';
import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded';
import { Link as RouterLink } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { IconTile, WorkspacePanel } from '../standalone/components';
import { ui } from '../standalone/theme';
import { useAiActive } from './CaseAiDraft';
import { HANDOFF_HOURS, handoffCopyText, handoffCounts, watchHref, watchLabel } from '../utils/shiftHandoff';
import type { ShiftHandoffNote } from '../types';

// The on-call handoff at the top of the Overview (backend/app/services/shift_handoff.py): counts
// for the last hours and what to watch first, ready to paste into the team's channel.

export function ShiftHandoffCard() {
  const [hours, setHours] = useState<number>(12);
  // The AI note for the window it was written for; changing the window drops it.
  const [note, setNote] = useState<{ hours: number; result: ShiftHandoffNote } | null>(null);
  const [copied, setCopied] = useState('');
  const aiActive = useAiActive();
  const query = useQuery({ queryKey: ['shift-handoff', hours], queryFn: () => api.shiftHandoff(hours), retry: false, refetchInterval: 60_000 });
  const write = useMutation({
    mutationFn: () => api.shiftHandoffNote(hours),
    onSuccess: (result) => setNote({ hours, result }),
    onError: () => setNote({ hours, result: { available: false, reason_code: 'failed' } }),
  });

  // Like the Overview's other extras: if this read fails, the page renders as it would without it.
  if (query.isError) return null;
  const handoff = query.data;
  const aiNote = note && note.hours === hours && note.result.available ? note.result.note : null;
  const noteFailed = note && note.hours === hours && !note.result.available;
  const [first, ...rest] = handoff?.watch ?? [];

  const copy = async () => {
    if (!handoff) return;
    try {
      await navigator.clipboard.writeText(handoffCopyText(handoff, aiNote, window.location.origin));
      setCopied('Copied. Paste it in your team channel.');
    } catch {
      setCopied("Couldn't copy: the browser blocked the clipboard.");
    }
  };

  return (
    <WorkspacePanel sx={{ p: 2.5 }}>
      <Box data-testid="shift-handoff">
        <Stack direction={{ xs: 'column', md: 'row' }} alignItems={{ xs: 'flex-start', md: 'center' }} justifyContent="space-between" spacing={1.5}>
          <Stack direction="row" alignItems="center" spacing={1.5}>
            <IconTile bg="var(--os-tint-blue)" color={ui.blue}><SwapHorizRoundedIcon /></IconTile>
            <Box>
              <Typography sx={{ fontWeight: 900, fontSize: 20 }}>Shift handoff</Typography>
              <Typography sx={{ color: ui.muted, fontSize: 13 }}>For the next person on call: what happened and what to watch first.</Typography>
            </Box>
          </Stack>
          <ToggleButtonGroup
            size="small"
            exclusive
            value={hours}
            onChange={(_, value: number | null) => {
              if (value) setHours(value);
              setCopied('');
            }}
            aria-label="Handoff window"
          >
            {HANDOFF_HOURS.map((value) => (
              <ToggleButton key={value} value={value} sx={{ textTransform: 'none', fontWeight: 800, px: 1.5 }}>Last {value}h</ToggleButton>
            ))}
          </ToggleButtonGroup>
        </Stack>

        {!handoff ? (
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 2, color: ui.muted }}><CircularProgress size={16} /><Typography>Loading the handoff...</Typography></Stack>
        ) : (
          <>
            <Typography data-testid="shift-handoff-counts" sx={{ mt: 2, fontWeight: 850 }}>{handoffCounts(handoff)}</Typography>

            {first ? (
              <Box sx={{ mt: 1.5, p: 1.75, borderRadius: '8px', border: `1px solid ${ui.orange}`, bgcolor: 'var(--os-tint-orange)' }} data-testid="shift-handoff-watch">
                <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', sm: 'center' }} spacing={1}>
                  <Box sx={{ minWidth: 0 }}>
                    <Typography sx={{ color: ui.orange, fontSize: 12, fontWeight: 900, textTransform: 'uppercase' }}>Watch first</Typography>
                    <Typography sx={{ fontWeight: 900 }}>{watchLabel(first)}</Typography>
                    <Typography sx={{ color: ui.text, fontSize: 14 }}>{first.title}: {first.reason}</Typography>
                  </Box>
                  <Button component={RouterLink} to={watchHref(first)} variant="outlined" sx={{ textTransform: 'none', fontWeight: 800, flexShrink: 0 }}>
                    {first.case_id ? 'Open case' : 'Open finding'}
                  </Button>
                </Stack>
              </Box>
            ) : (
              <Typography sx={{ mt: 1.5, color: ui.muted }}>Nothing open needs watching.</Typography>
            )}

            {rest.length ? (
              <Stack spacing={0.5} sx={{ mt: 1.25 }}>
                <Typography sx={{ color: ui.muted, fontSize: 12, fontWeight: 850 }}>Also worth a look</Typography>
                {rest.map((item) => (
                  <Button key={`${item.kind}-${item.case_id ?? item.finding_id}`} component={RouterLink} to={watchHref(item)} sx={{ justifyContent: 'flex-start', p: 0, textTransform: 'none', color: 'inherit' }}>
                    <Typography sx={{ fontSize: 14 }}><Box component="span" sx={{ fontWeight: 850 }}>{watchLabel(item)}</Box> · {item.reason}</Typography>
                  </Button>
                ))}
              </Stack>
            ) : null}

            {aiNote ? (
              <Box sx={{ mt: 1.75, p: 1.5, borderRadius: '8px', border: `1px solid ${ui.border}` }} data-testid="shift-handoff-note">
                <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
                  <Chip size="small" icon={<AutoAwesomeRoundedIcon />} label="AI" />
                  <Typography sx={{ color: ui.muted, fontSize: 12 }}>Written from the counts and list above. Check it before you paste.</Typography>
                </Stack>
                <Typography>{aiNote}</Typography>
                <Button size="small" onClick={() => setNote(null)} sx={{ mt: 0.5, p: 0, textTransform: 'none' }}>Show plain summary</Button>
              </Box>
            ) : null}
            {noteFailed ? <Alert severity="info" sx={{ mt: 1.5 }}>The AI note couldn't be written. The plain summary is still copied.</Alert> : null}

            <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 2 }} flexWrap="wrap" useFlexGap>
              <Tooltip describeChild title="Copies the note and the list with links. Paste it in your team channel at shift change.">
                <Button variant="contained" startIcon={<ContentCopyRoundedIcon />} onClick={copy} sx={{ textTransform: 'none', fontWeight: 800 }}>Copy for Slack</Button>
              </Tooltip>
              {aiActive ? (
                <Button variant="outlined" startIcon={write.isPending ? <CircularProgress size={14} /> : <AutoAwesomeRoundedIcon />} disabled={write.isPending} onClick={() => write.mutate()} sx={{ textTransform: 'none', fontWeight: 800 }}>
                  {aiNote ? 'Write again' : 'Write with AI'}
                </Button>
              ) : null}
              {copied ? <Typography role="status" sx={{ color: ui.muted, fontSize: 13 }}>{copied}</Typography> : null}
            </Stack>
          </>
        )}
      </Box>
    </WorkspacePanel>
  );
}
