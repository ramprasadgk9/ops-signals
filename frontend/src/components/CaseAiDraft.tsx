import { useState } from 'react';
import { Alert, Box, Button, Chip, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, Stack, Typography } from '@mui/material';
import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import type { CaseRcaDraft, CaseResolutionDraft } from '../types';

// "Draft from case" on a case's Root Cause and Resolution tabs (backend/app/services/case_ai_drafts.py).
// The draft fills the boxes and shows what it was written from; only the tab's own Save button saves.

type Draft = CaseRcaDraft | CaseResolutionDraft;

export type DraftField<T extends Draft> = {
  value: string;
  set: (value: string) => void;
  pick: (draft: T) => string | null | undefined;
};

/** Whether an AI provider is on, so the button is worth showing. */
export function useAiActive(): boolean {
  const status = useQuery({ queryKey: ['ai-status'], queryFn: () => api.aiStatus(), retry: false, refetchOnWindowFocus: false, staleTime: 5 * 60_000 });
  return status.data?.active === true;
}

export function useCaseDraft<T extends Draft>(suggest: () => Promise<T>, fields: DraftField<T>[]) {
  const [result, setResult] = useState<T | null>(null);
  // The boxes' text before the draft filled them, for Undo.
  const [previous, setPrevious] = useState<string[] | null>(null);
  const [confirming, setConfirming] = useState(false);
  const mutation = useMutation({
    mutationFn: suggest,
    onSuccess: (data) => {
      setResult(data);
      if (!data.available) return;
      setPrevious(fields.map((field) => field.value));
      fields.forEach((field) => {
        const text = field.pick(data);
        if (text) field.set(text);
      });
    },
    onError: () => setResult({ available: false, reason_code: 'failed' } as T),
  });
  return {
    result,
    drafted: Boolean(result?.available && previous),
    pending: mutation.isPending,
    confirming,
    request: () => (fields.some((field) => field.value.trim()) ? setConfirming(true) : mutation.mutate()),
    confirm: () => {
      setConfirming(false);
      mutation.mutate();
    },
    cancel: () => setConfirming(false),
    undo: () => {
      previous?.forEach((value, index) => fields[index].set(value));
      setPrevious(null);
      setResult(null);
    },
    /** After the tab's Save: the text is the person's now. */
    clear: () => {
      setPrevious(null);
      setResult(null);
    },
  };
}

type CaseDraft = ReturnType<typeof useCaseDraft>;

export function CaseDraftButton({ draft }: { draft: CaseDraft }) {
  return (
    <Stack direction="row" spacing={1} alignItems="center" justifyContent="flex-end" sx={{ mb: -1 }}>
      {draft.drafted ? <Chip size="small" color="secondary" variant="outlined" label="AI draft · not saved" data-testid="case-draft-chip" /> : null}
      <Button
        size="small"
        variant="outlined"
        color="secondary"
        onClick={draft.request}
        disabled={draft.pending}
        startIcon={draft.pending ? <CircularProgress size={14} color="inherit" /> : <AutoAwesomeRoundedIcon fontSize="small" />}
        sx={{ textTransform: 'none' }}
      >
        {draft.pending ? 'Drafting…' : draft.drafted ? 'Draft again' : 'Draft from case'}
      </Button>
      <Dialog open={draft.confirming} onClose={draft.cancel} aria-labelledby="case-draft-replace-title">
        <DialogTitle id="case-draft-replace-title">Replace your text?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">The draft replaces what's in the box now. You can undo it until you save.</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={draft.cancel} sx={{ textTransform: 'none' }}>Keep my text</Button>
          <Button onClick={draft.confirm} variant="contained" sx={{ textTransform: 'none' }}>Replace</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}

export function CaseDraftNotes({ draft, after }: { draft: CaseDraft; after?: string }) {
  const { result } = draft;
  if (!result) return null;
  if (draft.drafted) {
    return (
      <Box data-testid="case-draft-sources" sx={{ border: 1, borderColor: 'secondary.light', borderRadius: 1, px: 1.5, py: 1, bgcolor: 'action.hover' }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center">
          <Typography variant="body2" sx={{ fontWeight: 700 }}>Drafted from this case</Typography>
          <Button size="small" color="inherit" onClick={draft.undo} sx={{ textTransform: 'none', color: 'text.secondary' }}>Undo draft</Button>
        </Stack>
        <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
          {(result.sources ?? []).map((source, index) => (
            <li key={`${source.kind}-${index}`}>
              <Typography variant="body2" component="span">{source.label}</Typography>
              {source.detail ? <Typography variant="body2" component="span" color="text.secondary">{` · "${source.detail}"`}</Typography> : null}
            </li>
          ))}
        </Box>
        <Typography variant="caption" color="text.secondary">
          AI wrote this from the items above only. Check it{after ? `, then ${after}` : ''}.
        </Typography>
      </Box>
    );
  }
  if (result.reason_code === 'not_enough') {
    return <Alert severity="warning">Not enough on this case to draft from yet. Add an investigation note or link a ticket, then try again.</Alert>;
  }
  if (result.reason_code === 'ai_off') {
    return <Alert severity="info">AI drafts are off on this server.</Alert>;
  }
  return <Alert severity="warning">Couldn't write a draft this time. Try again, or write it yourself.</Alert>;
}
