import { useEffect, useMemo, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import {
  Alert,
  AlertTitle,
  Box,
  Button,
  Checkbox,
  Chip,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  LinearProgress,
  Link,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/queries';
import { useWebPermissions } from '../hooks/useWebPermissions';
import type { Finding } from '../types';
import { AI_SETUP } from '../utils/findingPlain';
import {
  DISCLAIMER,
  INVESTIGATE_AI_SETUP,
  INVESTIGATE_LIMITS,
  LATER_CHECKS,
  OPTIONAL_SOURCES,
  SHARED_WITH_AI,
  canContinue,
  endingBanner,
  investigationByline,
  isRunning,
  stepChecks,
  stepTag,
  type Investigation,
  type InvestigationStartInfo,
  type InvestigationStep,
  type StepMark,
} from '../utils/investigation';
import { ServiceNotesEditor, noteDraft, type NoteDraft } from './ServiceNotesEditor';

const POLL_MS = 1500;

type Props = { finding: Finding; open: boolean; onClose: () => void };

// Guided investigation of one finding (docs/investigate.md): first what the team knows and what it
// may look at, then the steps as it checks. It suggests where to look; a person confirms a cause.

export function InvestigateDialog({ finding, open, onClose }: Props) {
  const findingId = finding.id as number;
  const [investigationId, setInvestigationId] = useState<number | null>(null);
  const [startOver, setStartOver] = useState(false);
  const info = useQuery({ queryKey: ['investigation-start', findingId], queryFn: () => api.investigationStartInfo(findingId), enabled: open });

  useEffect(() => {
    if (!open) {
      setStartOver(false);
      setInvestigationId(null);
    }
  }, [open]);

  const currentId = startOver ? investigationId : investigationId ?? info.data?.latest?.id ?? null;
  const title = finding.plain?.headline ?? finding.title;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth aria-labelledby="investigate-title" data-testid="investigate-dialog">
      <DialogTitle id="investigate-title" sx={{ pb: 0.5 }}>
        Investigate: {title}
        <Typography variant="body2" color="text.secondary">
          {[finding.service, finding.metric_name].filter(Boolean).join(' · ')}
        </Typography>
      </DialogTitle>
      {info.isPending ? (
        <DialogContent>
          <LinearProgress />
        </DialogContent>
      ) : info.isError || !info.data ? (
        <DialogContent>
          <Alert severity="error">Couldn't load this finding's investigation. Try again.</Alert>
        </DialogContent>
      ) : currentId != null ? (
        <InvestigationView
          investigationId={currentId}
          findingId={findingId}
          aiOn={info.data.ai_on}
          onStartOver={() => {
            setInvestigationId(null);
            setStartOver(true);
          }}
          onClose={onClose}
        />
      ) : (
        <BeforeStart
          info={info.data}
          onStarted={(investigation) => {
            setStartOver(true);
            setInvestigationId(investigation.id);
          }}
          onClose={onClose}
        />
      )}
    </Dialog>
  );
}

function BeforeStart({ info, onStarted, onClose }: { info: InvestigationStartInfo; onStarted: (investigation: Investigation) => void; onClose: () => void }) {
  const { canEdit } = useWebPermissions();
  const queryClient = useQueryClient();
  const service = info.service ?? '';
  const [draft, setDraft] = useState<NoteDraft>(() => noteDraft(info.note));
  const [skipped, setSkipped] = useState<string[]>([]);
  const [today, setToday] = useState('');
  const [alwaysTrue, setAlwaysTrue] = useState(false);
  const suggestions = useQuery({
    queryKey: ['service-note-suggestions', service, info.connection_id],
    queryFn: () => api.serviceNoteSuggestions(service, info.connection_id),
    enabled: !!service && info.eligible,
    staleTime: 5 * 60_000,
  });
  const changed = useMemo(() => JSON.stringify(draft) !== JSON.stringify(noteDraft(info.note)), [draft, info.note]);

  const start = useMutation({
    mutationFn: async (saveNotes: boolean) => {
      if (saveNotes && changed) await api.saveServiceNote(service, draft);
      return api.startInvestigation({
        finding_id: info.finding_id,
        note: today.trim() || null,
        save_note: alwaysTrue && !!today.trim(),
        skipped_sources: skipped,
      });
    },
    onSuccess: (investigation) => {
      queryClient.invalidateQueries({ queryKey: ['investigation-start', info.finding_id] });
      onStarted(investigation);
    },
  });

  if (!info.ai_on) return <AiOff onClose={onClose} />;
  if (!info.eligible) {
    return (
      <>
        <DialogContent>
          <Alert severity="info">{info.reason}</Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Close</Button>
        </DialogActions>
      </>
    );
  }
  if (!canEdit) {
    return (
      <>
        <DialogContent>
          <Alert severity="info">Nobody has investigated this finding yet. Editors can start an investigation; you'll be able to read it here.</Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Close</Button>
        </DialogActions>
      </>
    );
  }

  const firstTime = !info.note.exists;
  return (
    <>
      <DialogContent sx={{ display: 'grid', gap: 2 }}>
        <ServiceNotesEditor service={service} note={info.note} draft={draft} onChange={setDraft} suggestions={suggestions.data ?? []} editable />

        <Box>
          <Typography sx={{ fontWeight: 800, fontSize: 14, mb: 0.5 }}>What it can look at</Typography>
          <FormControlLabel
            control={<Checkbox checked disabled size="small" />}
            label={
              <Typography variant="body2">
                <b>Prometheus{info.connection_name ? `: ${info.connection_name}` : ''}</b>
                <Typography component="span" variant="body2" color="text.secondary">
                  {' '}· where this finding came from{info.has_query ? ', with the query that found it' : ''}
                </Typography>
              </Typography>
            }
          />
          {OPTIONAL_SOURCES.map((source) => (
            <FormControlLabel
              key={source.key}
              sx={{ display: 'flex' }}
              control={
                <Checkbox
                  size="small"
                  checked={!skipped.includes(source.key)}
                  onChange={(event) => setSkipped(event.target.checked ? skipped.filter((key) => key !== source.key) : [...skipped, source.key])}
                />
              }
              label={
                <Typography variant="body2">
                  <b>{source.label}</b>
                  <Typography component="span" variant="body2" color="text.secondary">
                    {' '}· {source.detail}
                  </Typography>
                </Typography>
              }
            />
          ))}
        </Box>

        <Box>
          <Typography sx={{ fontWeight: 800, fontSize: 14, mb: 0.5 }}>
            Anything about today?{' '}
            <Typography component="span" variant="body2" color="text.secondary">
              (optional)
            </Typography>
          </Typography>
          <TextField
            fullWidth
            multiline
            minRows={2}
            size="small"
            value={today}
            onChange={(event) => setToday(event.target.value)}
            placeholder='e.g. "We turned on the new card provider for 10% of traffic this morning"'
            inputProps={{ 'aria-label': 'Anything about today?', maxLength: 1000 }}
          />
          <FormControlLabel
            control={<Checkbox size="small" checked={alwaysTrue} onChange={(event) => setAlwaysTrue(event.target.checked)} />}
            label={<Typography variant="body2" color="text.secondary">This is always true: also save it to what your team knows about {service}</Typography>}
          />
        </Box>

        <Typography variant="body2" color="text.secondary" sx={{ border: 1, borderStyle: 'dashed', borderColor: 'divider', borderRadius: 1, p: 1, fontSize: 12.5 }}>
          {DISCLAIMER} {INVESTIGATE_LIMITS} {SHARED_WITH_AI}
        </Typography>
        {start.isError ? <Alert severity="error">{(start.error as Error).message}</Alert> : null}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        {firstTime ? (
          <Button onClick={() => start.mutate(false)} disabled={start.isPending}>
            Skip, just start
          </Button>
        ) : null}
        <Button variant="contained" onClick={() => start.mutate(true)} disabled={start.isPending} data-testid="start-investigation">
          {start.isPending ? 'Starting…' : firstTime && changed ? 'Save and start investigating' : 'Start investigating'}
        </Button>
      </DialogActions>
    </>
  );
}

function InvestigationView({
  investigationId,
  findingId,
  aiOn,
  onStartOver,
  onClose,
}: {
  investigationId: number;
  findingId: number;
  aiOn: boolean;
  onStartOver: () => void;
  onClose: () => void;
}) {
  const { canEdit } = useWebPermissions();
  const queryClient = useQueryClient();
  const [message, setMessage] = useState('');
  const key = ['investigation', investigationId];
  const query = useQuery({
    queryKey: key,
    queryFn: () => api.getInvestigation(investigationId),
    refetchInterval: (current) => (isRunning(current.state.data) ? POLL_MS : false),
  });
  const update = (investigation: Investigation) => {
    queryClient.setQueryData(key, investigation);
    queryClient.invalidateQueries({ queryKey: ['investigation-start', findingId] });
  };
  const stop = useMutation({ mutationFn: () => api.stopInvestigation(investigationId), onSuccess: update });
  const proceed = useMutation({
    mutationFn: (text?: string) => api.continueInvestigation(investigationId, text),
    onSuccess: (investigation) => {
      setMessage('');
      update(investigation);
    },
  });
  const saveToCase = useMutation({
    mutationFn: async () => {
      const created = await api.createCase(findingId);
      return api.attachInvestigationToCase(investigationId, created.case_id);
    },
    onSuccess: update,
  });

  if (query.isPending) {
    return (
      <DialogContent>
        <LinearProgress />
      </DialogContent>
    );
  }
  if (query.isError || !query.data) {
    return (
      <DialogContent>
        <Alert severity="error">Couldn't load the investigation. Try again.</Alert>
      </DialogContent>
    );
  }

  const investigation = query.data;
  const running = isRunning(investigation);
  const banner = endingBanner(investigation);
  const roundChecks = investigation.checks.filter((check) => check.round === investigation.round);
  const editable = canEdit && aiOn;

  return (
    <>
      <DialogContent sx={{ display: 'grid', gap: 1.5 }}>
        <Typography variant="caption" color="text.secondary">
          {investigationByline(investigation)}
        </Typography>
        {running ? (
          <Box data-testid="investigation-running">
            <Stack direction="row" justifyContent="space-between" alignItems="center">
              <Typography sx={{ fontWeight: 700 }}>
                Checking… {roundChecks.length} of {investigation.check_budget} checks so far
              </Typography>
              {canEdit ? (
                <Button size="small" onClick={() => stop.mutate()} disabled={stop.isPending}>
                  Stop
                </Button>
              ) : null}
            </Stack>
            <LinearProgress sx={{ my: 1 }} />
            {roundChecks.map((check) => (
              <Typography key={check.ref} variant="body2" color="text.secondary">
                {check.ok ? '✓' : '⚠'} {check.purpose ?? check.tool}: {check.result.split('\n')[0]}
              </Typography>
            ))}
          </Box>
        ) : (
          <Alert severity={banner.severity} data-testid="investigation-ending">
            <AlertTitle sx={{ mb: banner.detail ? 0.5 : 0 }}>{banner.title}</AlertTitle>
            {banner.detail}
          </Alert>
        )}

        {investigation.summary ? (
          <Box>
            <Typography sx={{ fontWeight: 800, fontSize: 14 }}>What it found so far</Typography>
            <Typography variant="body2" data-testid="investigation-summary">
              {investigation.summary}
            </Typography>
          </Box>
        ) : null}

        {investigation.steps.length ? (
          <Box>
            <Typography sx={{ fontWeight: 800, fontSize: 14, mb: 1 }}>Steps</Typography>
            <Stack spacing={1}>
              {investigation.steps.map((step, index) => (
                <StepCard key={step.id} number={index + 1} step={step} investigation={investigation} editable={editable && !running} onUpdated={update} />
              ))}
            </Stack>
          </Box>
        ) : null}

        {editable && !running ? (
          <Stack direction="row" spacing={1}>
            <TextField
              size="small"
              fullWidth
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder='Ask or tell it something, e.g. "the report job is off today"'
              inputProps={{ 'aria-label': 'Ask or tell it something', maxLength: 1000 }}
            />
            <Button variant="outlined" disabled={!message.trim() || proceed.isPending} onClick={() => proceed.mutate(message.trim())}>
              Send
            </Button>
          </Stack>
        ) : null}
        {proceed.isError ? <Alert severity="error">{(proceed.error as Error).message}</Alert> : null}
        {saveToCase.isError ? <Alert severity="error">{(saveToCase.error as Error).message}</Alert> : null}
        <Typography variant="caption" color="text.secondary">
          {DISCLAIMER}
        </Typography>
      </DialogContent>
      <DialogActions sx={{ flexWrap: 'wrap', gap: 1 }}>
        {editable && !running ? (
          <Button onClick={onStartOver} sx={{ mr: 'auto' }}>
            Start over
          </Button>
        ) : null}
        <Button onClick={onClose}>Close</Button>
        {editable && !running && canContinue(investigation) ? (
          <Button variant="outlined" onClick={() => proceed.mutate(undefined)} disabled={proceed.isPending} data-testid="continue-investigation">
            {investigation.ending === 'budget' ? `Continue with ${LATER_CHECKS} more checks` : 'Keep going'}
          </Button>
        ) : null}
        {investigation.case_id ? (
          <Button variant="contained" component={RouterLink} to={`/cases/${investigation.case_id}?tab=investigation`}>
            Open case #{investigation.case_id} · Investigation
          </Button>
        ) : canEdit && !running ? (
          <Button variant="contained" onClick={() => saveToCase.mutate()} disabled={saveToCase.isPending} data-testid="save-to-case">
            {saveToCase.isPending ? 'Saving…' : 'Save to a case'}
          </Button>
        ) : null}
      </DialogActions>
    </>
  );
}

function StepCard({
  number,
  step,
  investigation,
  editable,
  onUpdated,
}: {
  number: number;
  step: InvestigationStep;
  investigation: Investigation;
  editable: boolean;
  onUpdated: (investigation: Investigation) => void;
}) {
  const [showQuery, setShowQuery] = useState(false);
  const [noting, setNoting] = useState(false);
  const [note, setNote] = useState(step.note ?? '');
  const tag = stepTag(step);
  const checks = stepChecks(step, investigation.checks);
  const mark = useMutation({
    mutationFn: (payload: { mark: StepMark | null; note?: string | null }) => api.markInvestigationStep(investigation.id, step.id, payload),
    onSuccess: (updated) => {
      setNoting(false);
      onUpdated(updated);
    },
  });
  const borderColor = step.mark === 'found' ? 'success.main' : step.status === 'worth_a_look' ? 'warning.main' : step.kind === 'your_step' ? 'info.main' : 'divider';

  return (
    <Box data-testid="investigation-step" sx={{ border: 1, borderColor: 'divider', borderLeft: 3, borderLeftColor: borderColor, borderRadius: 1, p: 1.25, opacity: step.status === 'ruled_out' && !step.mark ? 0.8 : 1 }}>
      <Stack direction="row" spacing={1} alignItems="baseline">
        <Typography sx={{ fontWeight: 800, color: 'text.secondary', width: 18 }}>{number}</Typography>
        <Typography sx={{ fontWeight: 700, flex: 1 }}>{step.title}</Typography>
        <Chip size="small" label={tag.label} color={tag.color} variant={tag.color === 'default' ? 'outlined' : 'filled'} />
      </Stack>
      <Box sx={{ pl: 3.25 }}>
        {step.why ? (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25 }}>
            Why: {step.why}
          </Typography>
        ) : null}
        {step.result ? (
          <Typography variant="body2" sx={{ mt: 0.5, whiteSpace: 'pre-wrap' }}>
            {step.result}
          </Typography>
        ) : null}
        {step.unverified ? (
          <Alert severity="warning" sx={{ mt: 0.75, py: 0 }}>
            Not checked: no check or past case of this investigation backs this step.
          </Alert>
        ) : null}
        {step.note ? (
          <Typography variant="body2" sx={{ mt: 0.5 }}>
            <b>Note{step.marked_by ? ` from ${step.marked_by}` : ''}:</b> {step.note}
          </Typography>
        ) : null}
        <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mt: 0.5, flexWrap: 'wrap' }}>
          {checks.length ? (
            <Link component="button" variant="body2" onClick={() => setShowQuery(!showQuery)}>
              {showQuery ? 'Hide query' : 'Show query'}
            </Link>
          ) : null}
          {step.evidence
            .filter((item) => item.startsWith('case #'))
            .map((item) => (
              <Link key={item} component={RouterLink} to={`/cases/${item.replace('case #', '')}`} variant="body2">
                Open {item}
              </Link>
            ))}
        </Stack>
        <Collapse in={showQuery}>
          {checks.map((check) => (
            <Box key={check.ref} sx={{ mt: 0.75 }}>
              <Typography variant="caption" color="text.secondary">
                {check.ref} · {check.tool}
                {check.purpose ? ` · ${check.purpose}` : ''}
              </Typography>
              <Box component="pre" sx={{ m: 0, p: 1, bgcolor: 'action.hover', borderRadius: 1, fontSize: 12, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
                {check.query ? `${check.query}\n\n` : ''}
                {check.result}
              </Box>
            </Box>
          ))}
        </Collapse>
        {editable ? (
          <Stack direction="row" spacing={1} sx={{ mt: 0.75 }}>
            <Button
              size="small"
              variant={step.mark === 'found' ? 'contained' : 'outlined'}
              color="success"
              onClick={() => mark.mutate({ mark: step.mark === 'found' ? null : 'found', note: step.note })}
              disabled={mark.isPending}
            >
              Found something
            </Button>
            <Button
              size="small"
              variant={step.mark === 'ruled_out' ? 'contained' : 'outlined'}
              color="inherit"
              onClick={() => mark.mutate({ mark: step.mark === 'ruled_out' ? null : 'ruled_out', note: step.note })}
              disabled={mark.isPending}
            >
              Ruled out
            </Button>
            <Button size="small" onClick={() => setNoting(!noting)}>
              {step.note ? 'Edit note' : 'Add note'}
            </Button>
          </Stack>
        ) : null}
        {noting ? (
          <Stack direction="row" spacing={1} sx={{ mt: 0.75 }}>
            <TextField size="small" fullWidth value={note} onChange={(event) => setNote(event.target.value)} inputProps={{ 'aria-label': `Note on step ${number}`, maxLength: 1000 }} />
            <Button size="small" variant="outlined" onClick={() => mark.mutate({ mark: step.mark, note: note.trim() || null })} disabled={mark.isPending}>
              Save
            </Button>
          </Stack>
        ) : null}
      </Box>
    </Box>
  );
}

function AiOff({ onClose }: { onClose: () => void }) {
  const { canAdmin } = useWebPermissions();
  return (
    <>
      <DialogContent>
        <Typography sx={{ fontWeight: 800, mb: 1 }}>Investigate needs an AI provider</Typography>
        <Typography variant="body2" sx={{ mb: 2 }}>
          {INVESTIGATE_AI_SETUP.intro}
        </Typography>
        <Typography variant="body2">
          {canAdmin
            ? 'Turn it on in Integrations → AI provider, with a hosted provider or a model you run yourself, then restart the backend.'
            : 'Ask an admin to turn on AI.'}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 2, fontSize: 13 }}>
          {INVESTIGATE_AI_SETUP.other} {canAdmin ? AI_SETUP.other : ''}
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
        {canAdmin ? (
          <Button component={RouterLink} to="/integrations" variant="contained">
            Open AI settings
          </Button>
        ) : null}
      </DialogActions>
    </>
  );
}
