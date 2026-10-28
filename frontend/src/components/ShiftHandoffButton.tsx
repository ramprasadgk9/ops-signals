import { useState } from 'react';
import { Alert, Box, Button, Chip, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, Stack, ToggleButton, ToggleButtonGroup, Tooltip, Typography } from '@mui/material';
import SwapHorizRoundedIcon from '@mui/icons-material/SwapHorizRounded';
import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded';
import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded';
import { Link as RouterLink } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { ui } from '../standalone/theme';
import { useAiActive } from './CaseAiDraft';
import { HANDOFF_HOURS, handoffCopyText, handoffCounts, openLabel, watchHref, watchLabel } from '../utils/shiftHandoff';
import type { ShiftHandoffNote } from '../types';

// Shift handoff (backend/app/services/shift_handoff.py): a button in the Overview's header that
// opens the handoff for the next person on call, ready to paste into the team's channel. A button,
// not a card: it's used at shift change, so it doesn't take the top of the page all day.

export function ShiftHandoffButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="outlined" color="warning" startIcon={<SwapHorizRoundedIcon />} onClick={() => setOpen(true)} sx={{ textTransform: 'none', fontWeight: 800 }}>
        Shift handoff
      </Button>
      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="sm" aria-labelledby="shift-handoff-title">
        {open ? <ShiftHandoffDialogBody onClose={() => setOpen(false)} /> : null}
      </Dialog>
    </>
  );
}

function ShiftHandoffDialogBody({ onClose }: { onClose: () => void }) {
  const [hours, setHours] = useState<number>(12);
  // The AI note for the window it was written for; changing the window drops it.
  const [note, setNote] = useState<{ hours: number; result: ShiftHandoffNote } | null>(null);
  const [copied, setCopied] = useState('');
  const aiActive = useAiActive();
  const query = useQuery({ queryKey: ['shift-handoff', hours], queryFn: () => api.shiftHandoff(hours), retry: false });
  const write = useMutation({
    mutationFn: () => api.shiftHandoffNote(hours),
    onSuccess: (result) => setNote({ hours, result }),
    onError: () => setNote({ hours, result: { available: false, reason_code: 'failed' } }),
  });

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
    <Box data-testid="shift-handoff">
      <DialogTitle id="shift-handoff-title" component="div">
        <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', sm: 'center' }} spacing={1}>
          <Box>
            <Typography sx={{ fontWeight: 900, fontSize: 20 }}>Shift handoff</Typography>
            <Typography sx={{ color: ui.muted, fontSize: 13 }}>For the next person on call: what happened and what to watch first.</Typography>
          </Box>
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
              <ToggleButton key={value} value={value} aria-label={`Last ${value}h`} sx={{ textTransform: 'none', fontWeight: 800, px: 1.5, whiteSpace: 'nowrap' }}>{value}h</ToggleButton>
            ))}
          </ToggleButtonGroup>
        </Stack>
      </DialogTitle>
      <DialogContent>
        {query.isError ? (
          <Alert severity="warning">The handoff could not be loaded. Check the backend connection and try again.</Alert>
        ) : !handoff ? (
          <Stack direction="row" spacing={1} alignItems="center" sx={{ color: ui.muted }}><CircularProgress size={16} /><Typography>Loading the handoff...</Typography></Stack>
        ) : (
          <>
            <Typography data-testid="shift-handoff-counts" sx={{ fontWeight: 850 }}>{handoffCounts(handoff)}</Typography>

            {first ? (
              <Box sx={{ mt: 1.5, p: 1.75, borderRadius: '8px', border: `1px solid ${ui.orange}`, bgcolor: 'var(--os-tint-orange)' }} data-testid="shift-handoff-watch">
                <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', sm: 'center' }} spacing={1}>
                  <Box sx={{ minWidth: 0 }}>
                    <Typography sx={{ color: ui.orange, fontSize: 12, fontWeight: 900, textTransform: 'uppercase' }}>Watch first</Typography>
                    <Typography sx={{ fontWeight: 900 }}>{watchLabel(first)}</Typography>
                    <Typography sx={{ color: ui.text, fontSize: 14 }}>{first.title}: {first.reason}</Typography>
                  </Box>
                  <Button component={RouterLink} to={watchHref(first)} onClick={onClose} variant="contained" sx={{ textTransform: 'none', fontWeight: 800, flexShrink: 0 }}>
                    {openLabel(first.kind)}
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
                  <Button key={`${item.kind}-${item.case_id ?? item.pattern_id ?? item.finding_id}`} component={RouterLink} to={watchHref(item)} onClick={onClose} sx={{ justifyContent: 'flex-start', p: 0, textTransform: 'none', color: 'inherit' }}>
                    <Typography sx={{ fontSize: 14, textAlign: 'left' }}><Box component="span" sx={{ fontWeight: 850 }}>{watchLabel(item)}</Box> · {item.reason}</Typography>
                  </Button>
                ))}
              </Stack>
            ) : null}

            {aiNote ? (
              <Box sx={{ mt: 1.75, p: 1.5, borderRadius: '8px', border: `1px solid ${ui.border}` }} data-testid="shift-handoff-note">
                <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
                  <Chip size="small" icon={<AutoAwesomeRoundedIcon />} label="AI" />
                  <Typography sx={{ color: ui.muted, fontSize: 12 }}>Counts by Ops Signals, the rest written by AI from the list above. Check it before you paste.</Typography>
                </Stack>
                <Typography>{aiNote}</Typography>
                <Button size="small" onClick={() => setNote(null)} sx={{ mt: 0.5, p: 0, textTransform: 'none' }}>Show plain summary</Button>
              </Box>
            ) : null}
            {noteFailed ? <Alert severity="info" sx={{ mt: 1.5 }}>The AI note couldn't be written. The plain summary is still copied.</Alert> : null}
          </>
        )}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2.5, justifyContent: 'flex-start', flexWrap: 'wrap', gap: 1 }}>
        <Tooltip describeChild title="Copies the note and the list with links. Paste it in your team channel at shift change.">
          <span>
            <Button variant="contained" startIcon={<ContentCopyRoundedIcon />} disabled={!handoff} onClick={copy} sx={{ textTransform: 'none', fontWeight: 800 }}>Copy for Slack</Button>
          </span>
        </Tooltip>
        {aiActive && handoff ? (
          <Button variant="outlined" startIcon={write.isPending ? <CircularProgress size={14} /> : <AutoAwesomeRoundedIcon />} disabled={write.isPending} onClick={() => write.mutate()} sx={{ textTransform: 'none', fontWeight: 800 }}>
            {aiNote ? 'Write again' : 'Write with AI'}
          </Button>
        ) : null}
        {copied ? <Typography role="status" sx={{ color: ui.muted, fontSize: 13 }}>{copied}</Typography> : null}
        <Box sx={{ flex: 1 }} />
        <Button onClick={onClose} sx={{ textTransform: 'none', fontWeight: 800 }}>Close</Button>
      </DialogActions>
    </Box>
  );
}
