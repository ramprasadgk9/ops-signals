import { useState } from 'react';
import { Box, Button, Chip, IconButton, MenuItem, Stack, TextField, Tooltip, Typography } from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import type { DependencyKind, DependencySuggestion, ServiceNote } from '../utils/investigation';
import { DEPENDENCY_KINDS } from '../utils/investigation';

export type NoteDraft = Pick<ServiceNote, 'depends_on' | 'behaviours' | 'dismissed' | 'owner' | 'channel' | 'runbook_url'>;

export function noteDraft(note: ServiceNote): NoteDraft {
  return {
    depends_on: note.depends_on,
    behaviours: note.behaviours,
    dismissed: note.dismissed,
    owner: note.owner,
    channel: note.channel,
    runbook_url: note.runbook_url,
  };
}

type Props = {
  service: string;
  note: ServiceNote;
  draft: NoteDraft;
  onChange: (draft: NoteDraft) => void;
  suggestions: DependencySuggestion[];
  editable: boolean;
};

// "What your team knows about <service>", edited in the Investigate dialog before Start: what the
// service depends on, behaviour that is normal for it, who owns it. Saved for everyone on Start.

export function ServiceNotesEditor({ service, note, draft, onChange, suggestions, editable }: Props) {
  const [name, setName] = useState('');
  const [kind, setKind] = useState<DependencyKind>('service');
  const [behaviour, setBehaviour] = useState('');
  const known = new Set([...draft.depends_on.map((item) => item.name), ...draft.dismissed]);
  const open = suggestions.filter((item) => !known.has(item.name));
  const firstTime = !note.exists;

  const addDependency = (dependency: { name: string; kind: DependencyKind }) =>
    onChange({ ...draft, depends_on: [...draft.depends_on, dependency] });

  return (
    <Box data-testid="service-notes" sx={{ border: 1, borderColor: 'secondary.light', bgcolor: 'action.hover', borderRadius: 2, p: 1.5 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="baseline" spacing={1}>
        <Typography sx={{ fontWeight: 800, fontSize: 14 }}>
          {firstTime ? 'Help it start in the right place' : `What your team knows about ${service}`}
        </Typography>
        {note.updated_by ? (
          <Typography variant="caption" color="text.secondary">
            updated by {note.updated_by}
          </Typography>
        ) : null}
      </Stack>
      {firstTime ? (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          Nobody has described <b>{service}</b> yet. A minute here saves checks now and on every later investigation.
        </Typography>
      ) : null}

      <Typography variant="body2" sx={{ fontWeight: 700, mt: 1 }}>
        {firstTime ? `What does ${service} depend on?` : 'Depends on'}
      </Typography>
      <Box sx={{ mt: 0.5 }}>
        {draft.depends_on.map((item) => (
          <Chip
            key={item.name}
            label={`${item.name} · ${DEPENDENCY_KINDS.find((entry) => entry.value === item.kind)?.label ?? item.kind}`}
            size="small"
            onDelete={editable ? () => onChange({ ...draft, depends_on: draft.depends_on.filter((other) => other.name !== item.name) }) : undefined}
            sx={{ mr: 0.5, mb: 0.5 }}
          />
        ))}
        {!draft.depends_on.length && !open.length ? (
          <Typography variant="body2" color="text.secondary">
            None written down yet.
          </Typography>
        ) : null}
      </Box>
      {open.map((item) => (
        <Stack key={item.name} direction="row" spacing={1} alignItems="center" data-testid="dependency-suggestion" sx={{ mt: 0.5, fontSize: 13 }}>
          <Typography variant="body2">
            <b>Suggested:</b> {item.name} <span style={{ opacity: 0.7 }}>· {item.kind} · from {item.label}</span>
          </Typography>
          {editable ? (
            <>
              <Button size="small" onClick={() => addDependency({ name: item.name, kind: item.kind })} sx={{ textTransform: 'none', minWidth: 0 }}>
                Add
              </Button>
              <Button
                size="small"
                color="inherit"
                onClick={() => onChange({ ...draft, dismissed: [...draft.dismissed, item.name] })}
                sx={{ textTransform: 'none', minWidth: 0, color: 'text.secondary' }}
              >
                Not a dependency
              </Button>
            </>
          ) : null}
        </Stack>
      ))}
      {editable ? (
        <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
          <TextField
            size="small"
            label="Add a dependency"
            placeholder="service, database, queue or outside API"
            value={name}
            onChange={(event) => setName(event.target.value)}
            sx={{ flex: 1 }}
          />
          <TextField select size="small" label="Kind" value={kind} onChange={(event) => setKind(event.target.value as DependencyKind)} sx={{ width: 150 }}>
            {DEPENDENCY_KINDS.map((entry) => (
              <MenuItem key={entry.value} value={entry.value}>
                {entry.label}
              </MenuItem>
            ))}
          </TextField>
          <Button
            size="small"
            disabled={!name.trim() || known.has(name.trim())}
            onClick={() => {
              addDependency({ name: name.trim(), kind });
              setName('');
            }}
          >
            Add
          </Button>
        </Stack>
      ) : null}

      <Typography variant="body2" sx={{ fontWeight: 700, mt: 1.5 }}>
        {firstTime ? `Anything that's normal for ${service} but looks odd?` : 'Known behaviour'}
      </Typography>
      {draft.behaviours.map((item, index) => (
        <Stack key={`${item.text}-${index}`} direction="row" spacing={1} alignItems="flex-start" sx={{ mt: 0.5 }}>
          <Typography variant="body2" sx={{ flex: 1 }}>
            {item.text}{' '}
            <Typography component="span" variant="caption" color="text.secondary">
              {item.case_id ? `· case #${item.case_id}` : item.by ? `· ${item.by}` : ''}
            </Typography>
          </Typography>
          {editable ? (
            <Tooltip title="Remove">
              <IconButton size="small" aria-label={`Remove "${item.text}"`} onClick={() => onChange({ ...draft, behaviours: draft.behaviours.filter((_, other) => other !== index) })}>
                <CloseIcon fontSize="inherit" />
              </IconButton>
            </Tooltip>
          ) : null}
        </Stack>
      ))}
      {editable ? (
        <Stack direction="row" spacing={1} sx={{ mt: 0.5 }}>
          <TextField
            size="small"
            fullWidth
            label="Add a line"
            placeholder='e.g. "the index rebuilds at 03:00 and latency doubles for 20 minutes"'
            value={behaviour}
            onChange={(event) => setBehaviour(event.target.value)}
          />
          <Button
            size="small"
            disabled={!behaviour.trim()}
            onClick={() => {
              onChange({ ...draft, behaviours: [...draft.behaviours, { text: behaviour.trim() }] });
              setBehaviour('');
            }}
          >
            Add
          </Button>
        </Stack>
      ) : null}

      {editable || draft.owner || draft.channel || draft.runbook_url ? (
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ mt: 1.5 }}>
          {(['owner', 'channel', 'runbook_url'] as const).map((field) => (
            <TextField
              key={field}
              size="small"
              label={{ owner: 'Owner', channel: 'Channel', runbook_url: 'Runbook link' }[field]}
              value={draft[field] ?? ''}
              onChange={(event) => onChange({ ...draft, [field]: event.target.value || null })}
              InputProps={{ readOnly: !editable }}
              sx={{ flex: 1 }}
            />
          ))}
        </Stack>
      ) : null}
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
        {editable ? 'Saved for everyone when you start.' : 'Editors can change these.'}
      </Typography>
    </Box>
  );
}
