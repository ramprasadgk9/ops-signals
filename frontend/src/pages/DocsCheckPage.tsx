import { useEffect, useState } from 'react';
import { Alert, Box, Button, Checkbox, Chip, CircularProgress, FormControlLabel, MenuItem, Stack, TextField, Typography } from '@mui/material';
import CheckRoundedIcon from '@mui/icons-material/CheckRounded';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link as RouterLink } from 'react-router-dom';
import { api } from '../api/queries';
import { ErrorState } from '../components/ErrorState';
import { WorkspacePanel } from '../standalone/components';
import { ui } from '../standalone/theme';
import type { DocCoverage, DocQuestionEvaluation, FlaggedQuestion, NewDocTest } from '../types';

export const DOCS_CHECK_PATH = '/assistant/docs-check';

// One question being checked: drafted for a doc, or brought over from thumbs-down feedback.
type Candidate = {
  key: string;
  question: string;
  sourcePath: string;
  section: string;
  phrase: string;
  origin: string;
  feedbackIds: number[];
  evaluation?: DocQuestionEvaluation;
  evaluationError?: string;
  verdict?: 'good' | 'wrong';
  save: boolean;
};

const reasonLabels: Record<string, string> = {
  wrong_section: 'Wrong section',
  missing_step: 'Missing a step',
  outdated: 'Outdated',
  not_in_docs: 'Not in the docs',
};

let nextKey = 0;
const newKey = () => `c${(nextKey += 1)}`;

function isKnownGap(candidate: Candidate): boolean {
  return candidate.verdict === 'wrong' || (candidate.evaluation !== undefined && !candidate.evaluation.cited_expected);
}

function toTest(candidate: Candidate): NewDocTest {
  return {
    question: candidate.question.trim(),
    source_path: candidate.sourcePath,
    section: candidate.section || null,
    contains: candidate.phrase.trim() ? [candidate.phrase.trim()] : [],
    known_gap: isKnownGap(candidate),
    feedback_ids: candidate.feedbackIds,
  };
}

export function DocsCheckPage() {
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ['knowledge-status'], queryFn: api.knowledgeStatus, retry: false });
  const coverage = useQuery({ queryKey: ['docs-coverage'], queryFn: api.docsCoverage, retry: false });
  const authoring = status.data?.docs_authoring_enabled ?? false;
  const flagged = useQuery({ queryKey: ['assistant-flagged'], queryFn: api.flaggedQuestions, enabled: authoring, retry: false });

  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const docs = coverage.data?.docs ?? [];
  const selectedDoc = docs.find((doc) => doc.source_path === selectedPath) ?? docs[0] ?? null;

  useEffect(() => {
    if (!selectedPath && docs.length) setSelectedPath(docs[0].source_path);
  }, [docs, selectedPath]);

  const update = (key: string, patch: Partial<Candidate>) =>
    setCandidates((current) => current.map((candidate) => (candidate.key === key ? { ...candidate, ...patch } : candidate)));

  const draft = useMutation({
    mutationFn: (sourcePath: string) => api.draftDocQuestions(sourcePath),
    onSuccess: (drafts) =>
      setCandidates((current) => [
        ...current,
        ...drafts.map((item) => ({
          key: newKey(),
          question: item.question,
          sourcePath: item.source_path,
          section: item.section,
          phrase: item.contains[0] ?? '',
          origin: item.drafted_by === 'headings' ? 'Drafted from headings (AI off) - edit to sound like a real question' : `Drafted by ${item.drafted_by}`,
          feedbackIds: [],
          save: false,
        })),
      ]),
  });

  const evaluate = useMutation({
    mutationFn: (candidate: Candidate) => api.evaluateDocQuestion({ question: candidate.question, source_path: candidate.sourcePath, section: candidate.section || null }),
    onSuccess: (evaluation, candidate) => update(candidate.key, { evaluation, evaluationError: undefined }),
    onError: (error, candidate) => update(candidate.key, { evaluationError: error instanceof Error ? error.message : 'Asking failed' }),
  });

  const addFlagged = (item: FlaggedQuestion) => {
    if (!selectedDoc) return;
    setCandidates((current) => [
      ...current,
      {
        key: newKey(),
        question: item.question,
        sourcePath: selectedDoc.source_path,
        section: selectedDoc.untested_sections[0] ?? '',
        phrase: '',
        origin: `From user feedback - flagged ${item.count}×. Pick the doc and section that should answer it.`,
        feedbackIds: item.feedback_ids,
        save: false,
      },
    ]);
  };

  const dismissFlagged = useMutation({
    mutationFn: (item: FlaggedQuestion) => Promise.all(item.feedback_ids.map((id) => api.updateAssistantFeedback(id, { status: 'dismissed' }))),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['assistant-flagged'] }),
  });

  const selected = candidates.filter((candidate) => candidate.save && candidate.question.trim());
  const selectedTests = selected.map(toTest);
  const preview = useQuery({
    queryKey: ['docs-check-preview', selectedTests],
    queryFn: () => api.saveDocTests(selectedTests, true),
    enabled: selectedTests.length > 0,
    retry: false,
  });
  const save = useMutation({
    mutationFn: () => api.saveDocTests(selectedTests, false),
    onSuccess: () => {
      setCandidates((current) => current.filter((candidate) => !candidate.save));
      queryClient.invalidateQueries({ queryKey: ['docs-coverage'] });
      queryClient.invalidateQueries({ queryKey: ['assistant-flagged'] });
    },
  });

  const asked = candidates.filter((candidate) => candidate.evaluation).length;
  const judged = candidates.filter((candidate) => candidate.verdict).length;
  const last = status.data?.last_bootstrap;
  const reindexed = last ? last.added.length + last.changed.length : null;

  return (
    <Box sx={{ pb: 3 }}>
      <WorkspacePanel sx={{ px: 3, py: 2.2, mb: 2 }}>
        <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={1.5}>
          <Box>
            <Button component={RouterLink} to="/assistant" size="small" sx={{ p: 0, textTransform: 'none' }}>← Ask Ops Signals</Button>
            <Typography sx={{ fontSize: 24, fontWeight: 900 }}>Check new docs</Typography>
            <Typography sx={{ color: ui.muted, fontSize: 14 }}>Make sure the assistant answers from the docs you added, then keep the good questions as tests.</Typography>
          </Box>
          {authoring ? <Chip label="Local authoring · OPS_SIGNALS_ALLOW_FILE_WRITES=true" sx={{ bgcolor: '#fff7e6', color: '#92400e', fontWeight: 750, alignSelf: 'flex-start' }} /> : null}
        </Stack>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(4, minmax(0, 1fr))' }, gap: 1.5, mt: 2 }}>
          <Step number={1} title="Reindexed" detail={reindexed === null ? 'Not in this session' : `${reindexed} docs changed`} done={reindexed !== null} />
          <Step number={2} title="Try questions" detail={`${asked} of ${candidates.length} asked`} active={candidates.length > 0 && asked < candidates.length} done={candidates.length > 0 && asked === candidates.length} />
          <Step number={3} title="Judge answers" detail={`${judged} judged`} active={asked > 0 && judged < asked} done={asked > 0 && judged >= asked} />
          <Step number={4} title="Save as tests" detail={`${selected.length} selected`} active={selected.length > 0} />
        </Box>
      </WorkspacePanel>

      {!authoring && status.isSuccess ? (
        <Alert severity="info" sx={{ mb: 2 }}>
          Saving questions writes <b>benchmark/assistant/golden_questions.yml</b>, so it needs a local checkout started with <b>OPS_SIGNALS_ALLOW_FILE_WRITES=true</b>
          (the dev scripts set it). You can still draft and ask questions here.
        </Alert>
      ) : null}
      {coverage.data && !coverage.data.golden_available ? (
        <Alert severity="warning" sx={{ mb: 2 }}>This server has no golden question file, so no doc shows tests. Packaged images don't include benchmark/; run Docs check from a local checkout.</Alert>
      ) : null}
      {coverage.isError ? <ErrorState message="Could not load docs coverage" /> : null}

      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: '320px minmax(0, 1fr)' }, gap: 2 }}>
        <WorkspacePanel sx={{ p: 2 }}>
          <Typography sx={{ fontWeight: 900 }}>Docs</Typography>
          {coverage.data ? (
            <Typography sx={{ fontSize: 13, color: ui.muted, mb: 1.2 }}>
              <b>{coverage.data.covered_docs} of {coverage.data.total_docs}</b> docs have at least one test.
            </Typography>
          ) : <CircularProgress size={18} sx={{ my: 1 }} />}
          <Stack spacing={1} sx={{ maxHeight: 420, overflowY: 'auto', pr: 0.5 }}>
            {docs.map((doc) => (
              <DocRow key={doc.source_path} doc={doc} selected={doc.source_path === selectedDoc?.source_path} onSelect={() => setSelectedPath(doc.source_path)} />
            ))}
          </Stack>

          {authoring ? (
            <>
              <Typography sx={{ fontWeight: 900, mt: 2.5 }}>Flagged by users</Typography>
              <Typography sx={{ fontSize: 13, color: ui.muted, mb: 1 }}>Answers marked as not answered.</Typography>
              {flagged.data?.length ? (
                <Stack spacing={1}>
                  {flagged.data.map((item) => (
                    <Box key={item.feedback_ids.join('-')} sx={{ p: 1.2, border: '1px solid #f3c9a8', bgcolor: '#fffaf5', borderRadius: '6px' }}>
                      <Typography sx={{ fontSize: 14, fontWeight: 650 }}>"{item.question}"</Typography>
                      <Typography sx={{ fontSize: 12, color: '#9a3412' }}>
                        Flagged {item.count}×{Object.keys(item.reasons).length ? ` · ${Object.keys(item.reasons).map((reason) => reasonLabels[reason] ?? reason).join(', ')}` : ''}
                      </Typography>
                      <Stack direction="row" spacing={1} sx={{ mt: 0.8 }}>
                        <Button size="small" variant="outlined" onClick={() => addFlagged(item)} disabled={!selectedDoc}>Add as test</Button>
                        <Button size="small" onClick={() => dismissFlagged.mutate(item)}>Dismiss</Button>
                      </Stack>
                    </Box>
                  ))}
                </Stack>
              ) : <Typography sx={{ fontSize: 13, color: ui.muted }}>Nothing flagged.</Typography>}
            </>
          ) : null}
        </WorkspacePanel>

        <WorkspacePanel sx={{ p: 2.4 }}>
          {selectedDoc ? (
            <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={1.5} sx={{ mb: 2 }}>
              <Box>
                <Typography sx={{ fontSize: 17, fontWeight: 900 }}>{selectedDoc.source_path}</Typography>
                <Typography sx={{ fontSize: 13, color: ui.muted }}>
                  {selectedDoc.section_count} sections · {selectedDoc.test_count} tests · {selectedDoc.untested_sections.length} sections untested
                </Typography>
              </Box>
              <Stack direction="row" spacing={1}>
                <Button variant="outlined" onClick={() => draft.mutate(selectedDoc.source_path)} disabled={draft.isPending} startIcon={draft.isPending ? <CircularProgress size={16} /> : undefined}>
                  {draft.isPending ? 'Drafting…' : 'Draft questions'}
                </Button>
                <Button
                  variant="outlined"
                  disabled={!candidates.length || evaluate.isPending}
                  onClick={() => candidates.filter((candidate) => !candidate.evaluation).forEach((candidate) => evaluate.mutate(candidate))}
                >
                  Ask all
                </Button>
              </Stack>
            </Stack>
          ) : null}
          {draft.isError ? <Alert severity="error" sx={{ mb: 2 }}>Drafting failed: {draft.error instanceof Error ? draft.error.message : 'unknown error'}</Alert> : null}
          {!candidates.length ? (
            <Alert severity="info">Draft questions for a doc, or add a flagged question, then ask each one to see which section the assistant answers from.</Alert>
          ) : (
            <Stack spacing={1.5}>
              {candidates.map((candidate) => (
                <CandidateCard
                  key={candidate.key}
                  candidate={candidate}
                  doc={docs.find((doc) => doc.source_path === candidate.sourcePath)}
                  docs={docs}
                  asking={evaluate.isPending && evaluate.variables?.key === candidate.key}
                  onAsk={() => evaluate.mutate(candidate)}
                  onChange={(patch) => update(candidate.key, { ...patch, ...('question' in patch || 'section' in patch || 'sourcePath' in patch ? { evaluation: undefined, verdict: undefined } : {}) })}
                  onDiscard={() => setCandidates((current) => current.filter((item) => item.key !== candidate.key))}
                  authoring={authoring}
                />
              ))}
            </Stack>
          )}

          {selected.length ? (
            <Box sx={{ mt: 2.5, pt: 2, borderTop: `1px solid ${ui.border}` }}>
              <Typography sx={{ fontSize: 13, fontWeight: 800, mb: 1 }}>Will be added to benchmark/assistant/golden_questions.yml</Typography>
              {preview.isError ? (
                <Alert severity="warning" sx={{ mb: 1 }}>{preview.error instanceof Error ? preview.error.message : 'These tests would not validate'}</Alert>
              ) : (
                <Box component="pre" sx={{ m: 0, p: 1.5, bgcolor: '#0f172a', color: '#e2e8f0', borderRadius: '6px', fontSize: 12, overflowX: 'auto' }}>
                  {preview.data?.yaml ?? 'Checking…'}
                </Box>
              )}
              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mt: 1.5 }}>
                <Typography sx={{ fontSize: 13, color: ui.muted }}>
                  {selected.length} selected{selected.some(isKnownGap) ? ' · wrong answers are saved as known gaps: recorded, not scored until they pass' : ''}
                </Typography>
                <Button variant="contained" disabled={!authoring || save.isPending || preview.isError || !preview.data} onClick={() => save.mutate()}>
                  {save.isPending ? 'Saving…' : `Save ${selected.length} ${selected.length === 1 ? 'test' : 'tests'}`}
                </Button>
              </Stack>
            </Box>
          ) : null}
          {save.isSuccess ? (
            <Alert severity="success" onClose={() => save.reset()} sx={{ mt: 2 }}>
              Saved {save.data.saved_ids.length} to {save.data.path}. Run <code>python -m benchmark.assistant_benchmark</code> to see them in the scores, and commit the file.
            </Alert>
          ) : null}
          {save.isError ? <Alert severity="error" sx={{ mt: 2 }}>Saving failed: {save.error instanceof Error ? save.error.message : 'unknown error'}</Alert> : null}
        </WorkspacePanel>
      </Box>
    </Box>
  );
}

function Step({ number, title, detail, done = false, active = false }: { number: number; title: string; detail: string; done?: boolean; active?: boolean }) {
  const tone = done ? { bg: '#effaf2', border: '#b7e4c4', dot: '#15803d' } : active ? { bg: '#eef0ff', border: '#4f46e5', dot: '#4f46e5' } : { bg: '#f8fafc', border: '#e2e8f0', dot: '#94a3b8' };
  return (
    <Stack direction="row" spacing={1.2} alignItems="center" sx={{ p: 1.2, bgcolor: tone.bg, border: `1px solid ${tone.border}`, borderRadius: '6px' }}>
      <Box sx={{ width: 26, height: 26, borderRadius: '50%', bgcolor: tone.dot, color: '#fff', fontSize: 13, fontWeight: 800, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        {done ? <CheckRoundedIcon sx={{ fontSize: 16 }} /> : number}
      </Box>
      <Box>
        <Typography sx={{ fontSize: 14, fontWeight: 750 }}>{title}</Typography>
        <Typography sx={{ fontSize: 12, color: ui.muted }}>{detail}</Typography>
      </Box>
    </Stack>
  );
}

function DocRow({ doc, selected, onSelect }: { doc: DocCoverage; selected: boolean; onSelect: () => void }) {
  return (
    <Button
      onClick={onSelect}
      aria-pressed={selected}
      sx={{ justifyContent: 'flex-start', textAlign: 'left', textTransform: 'none', p: 1.2, border: `1px solid ${selected ? '#4f46e5' : ui.border}`, bgcolor: selected ? '#f5f6ff' : '#fff', borderRadius: '6px', color: ui.text, display: 'block' }}
    >
      <Stack direction="row" spacing={1} alignItems="center">
        <Typography sx={{ fontSize: 14, fontWeight: 700, wordBreak: 'break-all' }}>{doc.source_path}</Typography>
        {doc.recently ? <Chip size="small" label={doc.recently === 'added' ? 'New' : 'Changed'} color="primary" sx={{ height: 20, fontSize: 11 }} /> : null}
      </Stack>
      <Typography sx={{ fontSize: 12, color: ui.muted }}>
        {doc.test_count ? `${doc.test_count} tests` : 'No tests'} · {doc.untested_sections.length} of {doc.section_count} sections untested
      </Typography>
    </Button>
  );
}

function CandidateCard({
  candidate,
  doc,
  docs,
  asking,
  onAsk,
  onChange,
  onDiscard,
  authoring,
}: {
  candidate: Candidate;
  doc?: DocCoverage;
  docs: DocCoverage[];
  asking: boolean;
  onAsk: () => void;
  onChange: (patch: Partial<Candidate>) => void;
  onDiscard: () => void;
  authoring: boolean;
}) {
  const evaluation = candidate.evaluation;
  const sections = Array.from(new Set([candidate.section, ...(doc?.untested_sections ?? [])].filter(Boolean)));
  const border = evaluation ? (evaluation.cited_expected ? '#b7e4c4' : '#f3c9a8') : ui.border;
  const first = evaluation?.cited[0];
  return (
    <Box sx={{ p: 1.8, border: `1px solid ${border}`, borderRadius: '8px' }}>
      <Typography sx={{ fontSize: 12, color: ui.muted, mb: 1 }}>{candidate.origin}</Typography>
      <Stack spacing={1.2}>
        <TextField label="Question" size="small" value={candidate.question} onChange={(event) => onChange({ question: event.target.value })} fullWidth />
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(3, minmax(0, 1fr))' }, gap: 1.2 }}>
          <TextField select label="Doc" size="small" value={candidate.sourcePath} onChange={(event) => onChange({ sourcePath: event.target.value, section: '' })}>
            {docs.map((item) => <MenuItem key={item.source_path} value={item.source_path}>{item.source_path}</MenuItem>)}
          </TextField>
          <TextField
            label="Section that should answer it"
            size="small"
            value={candidate.section}
            onChange={(event) => onChange({ section: event.target.value })}
            select={sections.length > 0}
          >
            {sections.map((section) => <MenuItem key={section} value={section}>{section}</MenuItem>)}
          </TextField>
          <TextField label="Answer must contain" size="small" value={candidate.phrase} onChange={(event) => onChange({ phrase: event.target.value })} placeholder="a command, setting or value" />
        </Box>
      </Stack>

      {evaluation ? (
        <Box sx={{ mt: 1.4 }}>
          {evaluation.cited_expected ? (
            <Chip size="small" label={`Cited the expected section${evaluation.rank && evaluation.rank > 1 ? ` (#${evaluation.rank})` : ''}`} sx={{ bgcolor: '#effaf2', color: '#14532d', fontWeight: 750 }} />
          ) : (
            <Chip size="small" label={first ? `Cited ${first.source_path}${first.section ? ` > ${first.section}` : ''} instead` : 'No documentation cited'} sx={{ bgcolor: '#fff4ec', color: '#9a3412', fontWeight: 750 }} />
          )}
          {first?.quote ? (
            <Typography sx={{ fontSize: 13, mt: 1, p: 1, bgcolor: '#f8fafc', borderRadius: '6px', whiteSpace: 'pre-wrap' }}>&gt; {first.quote}</Typography>
          ) : null}
          {!evaluation.cited_expected ? (
            <Typography sx={{ fontSize: 13, color: '#475569', mt: 1 }}>The section may need clearer wording, or keep the question as a known gap the assistant fails today.</Typography>
          ) : null}
        </Box>
      ) : null}
      {candidate.evaluationError ? <Alert severity="error" sx={{ mt: 1.2 }}>{candidate.evaluationError}</Alert> : null}

      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mt: 1.4 }}>
        <Button size="small" variant={evaluation ? 'outlined' : 'contained'} onClick={onAsk} disabled={asking || !candidate.question.trim()}>
          {asking ? 'Asking…' : evaluation ? 'Ask again' : 'Ask'}
        </Button>
        <Button size="small" variant={candidate.verdict === 'good' ? 'contained' : 'outlined'} color="success" disabled={!evaluation} onClick={() => onChange({ verdict: 'good', save: true })}>Good</Button>
        <Button size="small" variant={candidate.verdict === 'wrong' ? 'contained' : 'outlined'} color="warning" disabled={!evaluation} onClick={() => onChange({ verdict: 'wrong', save: true })}>Wrong</Button>
        <Button size="small" onClick={onDiscard}>Discard</Button>
        <FormControlLabel
          sx={{ ml: 'auto' }}
          control={<Checkbox checked={candidate.save} onChange={(event) => onChange({ save: event.target.checked })} disabled={!authoring} />}
          label={isKnownGap(candidate) ? 'Save as known gap' : 'Save as test'}
        />
      </Stack>
    </Box>
  );
}
