import { useState } from 'react';
import { Alert, Box, Button, Chip, CircularProgress, Collapse, Stack, TextField, Typography } from '@mui/material';
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/queries';
import type { CaseTimelineEvent, OperationalCase } from '../types';
import { CaseDraftButton, CaseDraftNotes, useCaseDraft } from './CaseAiDraft';
import { EnableAiHint } from './EnableAiHint';

// Publish Knowledge: the case's timeline (built from the case, no AI) and the write-up the next
// person reads, saved with the case and published to Operational Memory with it.

const DOT: Record<CaseTimelineEvent['kind'], string> = {
  deploy: 'primary.main',
  finding: 'warning.main',
  opened: 'text.disabled',
  ticket: 'text.disabled',
  note: 'text.disabled',
  ticket_comment: 'text.disabled',
  resolved: 'success.main',
};

function eventTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function eventText(event: CaseTimelineEvent): { text: string; source: string | null } {
  if (event.kind === 'ticket_comment') return { text: `"${event.text}"`, source: [event.who, 'ticket'].filter(Boolean).join(', ') };
  if (event.kind === 'note') return { text: `"${event.text}"`, source: event.who ? `note, ${event.who}` : 'note' };
  return { text: event.text, source: event.who ?? null };
}

function durationText(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return minutes % 60 ? `${hours} h ${minutes % 60} min` : `${hours} h`;
}

export function CaseTimelineList({ caseId }: { caseId: number }) {
  const timeline = useQuery({ queryKey: ['case-timeline', caseId], queryFn: () => api.caseTimeline(caseId), retry: false });
  if (timeline.isPending) return <CircularProgress size={20} />;
  if (timeline.isError) return <Alert severity="warning">Couldn't load the timeline.</Alert>;
  const { events, time_to_fix_minutes: minutes } = timeline.data;
  if (!events.length) return <Typography variant="body2" color="text.secondary">Nothing with a time on this case yet.</Typography>;
  return (
    <Box data-testid="case-timeline">
      <Box component="ul" sx={{ listStyle: 'none', m: 0, p: 0, ml: 0.75, borderLeft: 2, borderColor: 'divider' }}>
        {events.map((event, index) => {
          const { text, source } = eventText(event);
          return (
            <Box component="li" key={`${event.time}-${index}`} sx={{ position: 'relative', pl: 2.25, pb: 1.25 }}>
              <Box sx={{ position: 'absolute', left: -7, top: 6, width: 12, height: 12, borderRadius: '50%', bgcolor: 'background.paper', border: 2, borderColor: DOT[event.kind] }} />
              <Typography variant="caption" color="text.secondary" sx={{ mr: 1, fontVariantNumeric: 'tabular-nums' }}>
                {eventTime(event.time)}
              </Typography>
              <Typography variant="body2" component="span">{text}</Typography>
              {source ? <Typography variant="caption" color="text.secondary">{` · ${source}`}</Typography> : null}
            </Box>
          );
        })}
      </Box>
      {minutes != null ? (
        <Typography variant="caption" color="text.secondary">Time to fix: {durationText(minutes)} from the first finding.</Typography>
      ) : null}
    </Box>
  );
}

function MemoryText({ caseId }: { caseId: number }) {
  const [open, setOpen] = useState(false);
  const timeline = useQuery({ queryKey: ['case-timeline', caseId], queryFn: () => api.caseTimeline(caseId), retry: false });
  if (!timeline.data) return null;
  return (
    <Box sx={{ borderTop: 1, borderColor: 'divider', pt: 1 }}>
      <Button size="small" onClick={() => setOpen((value) => !value)} sx={{ textTransform: 'none', px: 0 }}>
        {open ? 'Hide what future searches will read' : 'What future searches will read'}
      </Button>
      <Collapse in={open}>
        <Box component="pre" data-testid="case-memory-text" sx={{ m: 0, mt: 0.5, p: 1.5, borderRadius: 1, bgcolor: 'action.hover', fontSize: 12, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
          {timeline.data.memory_text}
        </Box>
      </Collapse>
    </Box>
  );
}

export function CaseWriteup({
  caseData,
  canEdit,
  canAdmin,
  aiActive,
  onPublish,
  onSaved,
  onNext,
}: {
  caseData: OperationalCase;
  canEdit: boolean;
  canAdmin: boolean;
  aiActive: boolean;
  /** Publishes the case to Operational Memory. */
  onPublish: () => Promise<unknown>;
  /** After the write-up was saved (and maybe published): refresh the case. */
  onSaved: () => void;
  onNext: () => void;
}) {
  const queryClient = useQueryClient();
  const saved = caseData.writeup ?? '';
  const [text, setText] = useState(saved);
  const [editing, setEditing] = useState(!saved);
  const draft = useCaseDraft(() => api.suggestWriteup(caseData.id), [{ value: text, set: setText, pick: (result) => result.draft }]);
  const dirty = text.trim() !== saved.trim();

  const save = useMutation({
    mutationFn: async (publish: boolean) => {
      await api.updateWriteup(caseData.id, text);
      if (publish) await onPublish();
    },
    onSuccess: () => {
      draft.clear();
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ['case-timeline', caseData.id] });
      onSaved();
    },
  });
  const publishOnly = useMutation({
    mutationFn: onPublish,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case-timeline', caseData.id] });
      onSaved();
    },
  });

  const status = caseData.memory_status;
  const busy = save.isPending || publishOnly.isPending;
  const showDraft = canEdit && aiActive;

  return (
    <Stack spacing={2}>
      <Box>
        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>Timeline</Typography>
        <Typography variant="caption" color="text.secondary" component="div" sx={{ mb: 1 }}>
          Built from the case, no AI. Times in your time zone.
        </Typography>
        <CaseTimelineList caseId={caseData.id} />
      </Box>

      <Box>
        {editing && canEdit ? (
          <Stack spacing={1.5}>
            {showDraft ? <CaseDraftButton draft={draft} label="Draft write-up" /> : null}
            <TextField
              label="Summary and lessons"
              multiline
              minRows={6}
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="What happened, what fixed it, and what's still open."
              helperText="Optional, and makes the case much easier to reuse. Saved with the case and published to memory with it."
            />
            <CaseDraftNotes draft={draft} after="save" notEnough="Save a root cause or a resolution first; the write-up is drafted from them." />
            {!aiActive && canAdmin ? (
              <EnableAiHint text="Turn on AI to draft this write-up from the saved root cause, resolution and timeline." title="Turn on AI drafts" />
            ) : null}
          </Stack>
        ) : (
          <Box>
            <Stack direction="row" justifyContent="space-between" alignItems="center">
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>Summary and lessons</Typography>
              {canEdit ? <Button size="small" onClick={() => setEditing(true)} sx={{ textTransform: 'none' }}>Edit</Button> : null}
            </Stack>
            {saved ? (
              <Typography variant="body2" data-testid="case-writeup-saved" sx={{ whiteSpace: 'pre-wrap', bgcolor: 'action.hover', borderRadius: 1, p: 1.5 }}>
                {saved}
              </Typography>
            ) : (
              <Typography variant="body2" color="text.secondary">No write-up yet.</Typography>
            )}
          </Box>
        )}
      </Box>

      {status === 'stale' ? <Alert severity="warning">The case changed after publishing. Publish again so future searches find the new text.</Alert> : null}
      {status === 'indexed' && !dirty ? <Alert severity="success">Published. Future similar-case searches include this case and its write-up.</Alert> : null}
      {status === 'failed' ? <Alert severity="error">Publishing failed. Try again.</Alert> : null}
      {save.isError || publishOnly.isError ? <Alert severity="error">Couldn't save or publish. Try again.</Alert> : null}

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
        {dirty ? (
          <>
            <Button variant="contained" onClick={() => save.mutate(true)} disabled={busy || !canEdit}>
              {save.isPending ? <CircularProgress size={20} sx={{ mr: 1 }} /> : null}
              Save and publish
            </Button>
            <Button variant="outlined" onClick={() => save.mutate(false)} disabled={busy || !canEdit}>
              Save only
            </Button>
          </>
        ) : (
          <Button variant="contained" onClick={() => publishOnly.mutate()} disabled={busy || status === 'indexed' || !canEdit}>
            {publishOnly.isPending ? <CircularProgress size={20} sx={{ mr: 1 }} /> : null}
            {status === 'indexed' ? 'Published' : status === 'stale' ? 'Publish again' : 'Publish Knowledge'}
          </Button>
        )}
        <Button variant="outlined" onClick={onNext} endIcon={<ArrowForwardRoundedIcon />}>
          Next: Similar Cases
        </Button>
      </Stack>

      <MemoryText caseId={caseData.id} />
    </Stack>
  );
}

export function WriteupChip({ status }: { status: string }) {
  const label = status === 'indexed' ? 'Published' : status === 'stale' ? 'Needs refresh' : status === 'failed' ? 'Publish failed' : 'Not published';
  const color = status === 'indexed' ? 'success' : status === 'stale' ? 'warning' : status === 'failed' ? 'error' : 'default';
  return <Chip label={label} color={color} />;
}
