import { useMemo, useState } from 'react';
import { Alert, AlertTitle, Badge, Box, Button, Card, CardContent, Chip, CircularProgress, Divider, IconButton, Popover, Stack, TextField, Typography } from '@mui/material';
import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded';
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded';
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded';
import SendRoundedIcon from '@mui/icons-material/SendRounded';
import SyncRoundedIcon from '@mui/icons-material/SyncRounded';
import OpenInNewRoundedIcon from '@mui/icons-material/OpenInNewRounded';
import HelpOutlineRoundedIcon from '@mui/icons-material/HelpOutlineRounded';
import ThumbUpOffAltRoundedIcon from '@mui/icons-material/ThumbUpOffAltRounded';
import ThumbDownOffAltRoundedIcon from '@mui/icons-material/ThumbDownOffAltRounded';
import ThumbUpAltRoundedIcon from '@mui/icons-material/ThumbUpAltRounded';
import ThumbDownAltRoundedIcon from '@mui/icons-material/ThumbDownAltRounded';
import FlagOutlinedIcon from '@mui/icons-material/FlagOutlined';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link as RouterLink } from 'react-router-dom';
import { api } from '../api/queries';
import { ErrorState } from '../components/ErrorState';
import { DOCS_CHECK_PATH } from './DocsCheckPage';
import { LoadDemoDataButton } from '../components/IntegrationActions';
import { WorkspacePanel } from '../standalone/components';
import { ui } from '../standalone/theme';
import type { AssistantChatResponse, AssistantEvidenceGroup, AssistantFeedbackReason, KnowledgeChanges, KnowledgeReindexResult, KnowledgeStatus } from '../types';

type ChatMessage = {
  role: 'user' | 'assistant';
  content: string;
  response?: AssistantChatResponse;
  // Assistant messages: the question they answer, for feedback.
  question?: string;
};

// Docs are always there, so these always have an answer. "About your systems" examples come from
// this install's own findings and cases (GET /api/assistant/starter-questions).
const docsPrompts = [
  'How do I turn on API authentication?',
  'Where do I point my OTel Collector?',
  'How does Behavior Intelligence work?',
  'Which analyzers are there and what does each find?',
];

const feedbackReasons: Array<{ value: AssistantFeedbackReason; label: string }> = [
  { value: 'wrong_section', label: 'Wrong section' },
  { value: 'missing_step', label: 'Missing a step' },
  { value: 'outdated', label: 'Outdated' },
  { value: 'not_in_docs', label: 'Not in the docs' },
];

function sourceLabel(sourceType: string) {
  if (sourceType === 'case' || sourceType === 'historical_case') return 'Case';
  if (sourceType === 'finding') return 'Finding';
  if (sourceType === 'behavior') return 'Behavior';
  if (sourceType === 'app_documentation') return 'Doc';
  return sourceType;
}

function evidenceGroups(result: AssistantChatResponse | null): AssistantEvidenceGroup[] {
  if (result?.evidence_groups?.length) return result.evidence_groups;
  const sources = result?.sources ?? [];
  if (!sources.length) return [];
  const grouped = new Map<string, AssistantEvidenceGroup>();
  for (const source of sources) {
    const label = sourceLabel(source.source_type);
    const group = grouped.get(label) ?? { source_type: source.source_type, label, count: 0, sources: [] };
    group.sources.push(source);
    group.count = group.sources.length;
    grouped.set(label, group);
  }
  return Array.from(grouped.values());
}

export function MemoryChatPage() {
  const [message, setMessage] = useState('');
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  const latestAssistant = [...messages].reverse().find((item) => item.role === 'assistant')?.response ?? null;
  const groups = useMemo(() => evidenceGroups(latestAssistant), [latestAssistant]);

  const sendMessage = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    mutation.mutate(trimmed);
  };

  const mutation = useMutation({
    mutationFn: (text: string) =>
      api.assistantChat({
        conversation_id: conversationId,
        message: text,
        top_k: 6,
        minimum_score: 0.35,
        same_service_only: false,
      }),
    onMutate: (text) => {
      setMessages((current) => [...current, { role: 'user', content: text }]);
      setMessage('');
    },
    onSuccess: (data, text) => {
      setConversationId(data.conversation_id);
      setMessages((current) => [...current, { role: 'assistant', content: data.answer, response: data, question: text }]);
    },
  });

  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ['knowledge-status'], queryFn: api.knowledgeStatus, retry: false });
  const authoring = status.data?.docs_authoring_enabled ?? false;
  const flagged = useQuery({ queryKey: ['assistant-flagged'], queryFn: api.flaggedQuestions, enabled: authoring, retry: false });
  const reindex = useMutation({
    mutationFn: () => api.reindexKnowledge(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge-status'] });
      queryClient.invalidateQueries({ queryKey: ['docs-coverage'] });
    },
  });
  const [dismissedPending, setDismissedPending] = useState<string | null>(null);
  const pending = status.data?.pending_changes ?? null;
  const pendingCount = pending ? pending.added.length + pending.changed.length + pending.removed.length : 0;
  const pendingKey = pending ? JSON.stringify(pending) : '';
  const flaggedCount = flagged.data?.length ?? 0;

  const regenerate = () => {
    const lastUser = [...messages].reverse().find((item) => item.role === 'user');
    if (lastUser) sendMessage(lastUser.content);
  };

  return (
    <Box sx={{ pb: 3, height: { xl: 'calc(100vh - 120px)' }, minHeight: { xl: 680 } }}>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', xl: 'minmax(0, 1fr) 360px' }, gap: 2, height: '100%' }}>
        {/* Stacked below xl: the chat gets its own height instead of sharing one window-high box with the evidence panel. */}
        <WorkspacePanel sx={{ display: 'flex', flexDirection: 'column', minHeight: { xs: 640, xl: 0 }, height: { xs: 'calc(100vh - 120px)', xl: 'auto' }, overflow: 'hidden' }}>
          <Box sx={{ px: 3, py: 2.2, borderBottom: `1px solid ${ui.border}` }}>
            <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={1.5}>
              <Box>
                <Typography sx={{ fontSize: 24, fontWeight: 900, color: ui.text }}>Ask Ops Signals</Typography>
                <Typography sx={{ color: ui.muted, fontSize: 14 }}>Operational assistant for cases, findings, memory, behavior intelligence, and docs.</Typography>
              </Box>
              <Stack direction="row" spacing={1}>
                <Button startIcon={<RefreshRoundedIcon />} variant="outlined" onClick={regenerate} disabled={!messages.some((item) => item.role === 'user') || mutation.isPending}>Regenerate</Button>
                <Button startIcon={<DeleteOutlineRoundedIcon />} variant="outlined" onClick={() => { setMessages([]); setConversationId(null); }}>Clear</Button>
                <Badge badgeContent={reindex.isPending ? 0 : pendingCount} color="primary" overlap="rectangular">
                  <Button
                    startIcon={reindex.isPending ? <CircularProgress size={16} /> : <SyncRoundedIcon />}
                    variant="outlined"
                    onClick={() => reindex.mutate()}
                    disabled={reindex.isPending}
                    sx={{ whiteSpace: 'nowrap' }}
                  >
                    {reindex.isPending ? 'Reindexing…' : 'Reindex docs'}
                  </Button>
                </Badge>
                <ReindexHelp />
              </Stack>
            </Stack>
            {authoring && flaggedCount ? (
              <Button component={RouterLink} to={DOCS_CHECK_PATH} size="small" startIcon={<FlagOutlinedIcon />} sx={{ mt: 1, textTransform: 'none', fontWeight: 750 }}>
                {flaggedCount} {flaggedCount === 1 ? 'question' : 'questions'} flagged as not answered - review in Docs check
              </Button>
            ) : null}
            {reindex.isSuccess ? (
              <ReindexResultBanner result={reindex.data} authoring={authoring} onClose={() => reindex.reset()} />
            ) : null}
            {reindex.isError ? (
              <Alert severity="error" onClose={() => reindex.reset()} sx={{ mt: 1.5 }}>Reindex failed: {reindex.error instanceof Error ? reindex.error.message : 'unknown error'}</Alert>
            ) : null}
            {!reindex.isSuccess && !reindex.isPending && pending && pendingCount && dismissedPending !== pendingKey ? (
              <Alert
                severity="info"
                onClose={() => setDismissedPending(pendingKey)}
                action={<Button color="inherit" size="small" onClick={() => reindex.mutate()} sx={{ fontWeight: 800, whiteSpace: 'nowrap' }}>Reindex now</Button>}
                sx={{ mt: 1.5 }}
              >
                <b>{pendingCount} {pendingCount === 1 ? 'doc' : 'docs'} changed</b> since the assistant last read them ({listPaths(pending)}). Its answers won't include those changes until you reindex.
              </Alert>
            ) : null}
          </Box>

          <Box sx={{ flex: 1, overflowY: 'auto', px: { xs: 2, md: 5 }, py: 3, bgcolor: 'var(--os-surface)' }}>
            {!messages.length ? (
              <Stack spacing={2.5} sx={{ maxWidth: 760, mx: 'auto', mt: 4 }}>
                <Box>
                  <Typography sx={{ fontSize: 26, fontWeight: 900 }}>What can I ask?</Typography>
                  <Typography sx={{ color: ui.muted }}>Answers show the evidence they come from: a finding, a case, or the doc section they quote.</Typography>
                </Box>
                <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(2, minmax(0, 1fr))' }, gap: 2 }}>
                  <SystemsExamples onAsk={sendMessage} />
                  <Box sx={{ p: 2, border: `1px solid ${ui.border}`, borderRadius: '8px', bgcolor: 'var(--os-surface)' }}>
                    <Typography sx={{ fontWeight: 850 }}>About Ops Signals</Typography>
                    <Typography sx={{ color: ui.muted, fontSize: 13, mb: 1.2 }}>Setup and features, answered from the docs</Typography>
                    <Stack spacing={1} alignItems="flex-start">
                      {docsPrompts.map((prompt) => <Chip key={prompt} label={prompt} clickable onClick={() => sendMessage(prompt)} sx={{ fontWeight: 700 }} />)}
                    </Stack>
                  </Box>
                </Box>
              </Stack>
            ) : (
              <Stack spacing={2.2} sx={{ maxWidth: 900, mx: 'auto' }}>
                {messages.map((item, index) => (
                  <Box key={index} sx={{ alignSelf: item.role === 'user' ? 'flex-end' : 'stretch', maxWidth: item.role === 'user' ? '72%' : '100%' }}>
                    {item.role === 'assistant' ? <KnowledgeUsed response={item.response} /> : null}
                    <Box sx={{ px: 2, py: 1.6, borderRadius: '12px', bgcolor: item.role === 'user' ? '#0f766e' : 'var(--os-surface)', color: item.role === 'user' ? '#fff' : ui.text, border: item.role === 'assistant' ? `1px solid ${ui.border}` : 'none' }}>
                      <Typography sx={{ whiteSpace: 'pre-line', lineHeight: 1.65 }}>{item.content}</Typography>
                      {item.role === 'assistant' ? (
                        <Stack direction="row" spacing={0.5} sx={{ mt: 1 }}>
                          <IconButton size="small" aria-label="Copy answer" onClick={() => navigator.clipboard?.writeText(item.content)}><ContentCopyRoundedIcon fontSize="small" /></IconButton>
                        </Stack>
                      ) : null}
                      {item.role === 'assistant' && item.response && item.question ? (
                        <AnswerFeedback question={item.question} response={item.response} conversationId={conversationId} />
                      ) : null}
                    </Box>
                    {item.response?.suggested_questions?.length ? (
                      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>
                        {item.response.suggested_questions.map((question) => (
                          <Chip key={question} label={question} size="small" clickable onClick={() => sendMessage(question)} />
                        ))}
                      </Stack>
                    ) : null}
                  </Box>
                ))}
                {mutation.isPending ? (
                  <Stack direction="row" spacing={1.5} alignItems="center" sx={{ color: ui.muted }}>
                    <CircularProgress size={18} />
                    <Typography>Routing question and collecting operational evidence...</Typography>
                  </Stack>
                ) : null}
              </Stack>
            )}
            {mutation.isError ? <ErrorState message="Assistant failed to collect operational evidence" /> : null}
          </Box>

          <Box sx={{ p: 2, borderTop: `1px solid ${ui.border}`, bgcolor: 'var(--os-surface)' }}>
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.2}>
              <TextField
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    sendMessage(message);
                  }
                }}
                placeholder="Ask about cases, findings, behavior patterns, memory, analyzers..."
                fullWidth
                multiline
                maxRows={4}
              />
              <Button variant="contained" endIcon={<SendRoundedIcon />} disabled={mutation.isPending || !message.trim()} onClick={() => sendMessage(message)} sx={{ px: 3, bgcolor: '#009688', fontWeight: 850 }}>
                Send
              </Button>
            </Stack>
          </Box>
        </WorkspacePanel>

        <WorkspacePanel sx={{ p: 2.2, overflowY: 'auto', minHeight: 0 }}>
          <Typography sx={{ fontSize: 18, fontWeight: 900, mb: 0.5 }}>Evidence</Typography>
          <Typography sx={{ color: ui.muted, fontSize: 13, mb: 2 }}>Synchronized with the latest assistant answer.</Typography>
          {!latestAssistant ? (
            <Alert severity="info">Evidence will appear here after you ask a question.</Alert>
          ) : groups.length ? (
            <Stack spacing={1.5}>
              {groups.map((group) => (
                <EvidenceGroup key={`${group.label}-${group.source_type}`} group={group} />
              ))}
            </Stack>
          ) : (
            <Alert severity="warning">No operational evidence found for the latest answer.</Alert>
          )}
          <KnowledgeCard status={status.data} pendingCount={pendingCount} />
          {!latestAssistant ? <TipsCard /> : null}
        </WorkspacePanel>
      </Box>
    </Box>
  );
}

function KnowledgeUsed({ response }: { response?: AssistantChatResponse }) {
  const used = response?.knowledge_used ?? [];
  return (
    <Stack direction="row" spacing={0.8} flexWrap="wrap" useFlexGap sx={{ mb: 0.8 }}>
      <Chip size="small" label={`Intent: ${response?.intent ?? 'routing'}`} variant="outlined" />
      {used.length ? (
        <Chip
          size="small"
          label={response?.ai_synthesis_used ? 'AI-generated' : 'Evidence summary (no AI)'}
          sx={response?.ai_synthesis_used ? { bgcolor: '#f5f3ff', color: '#6d28d9', fontWeight: 750 } : { bgcolor: 'var(--os-surface-alt)', color: 'var(--os-text-2)', fontWeight: 750 }}
        />
      ) : null}
      {used.length ? used.map((item) => <Chip key={item} size="small" label={`✓ ${item}`} sx={{ bgcolor: 'var(--os-tint-green)', color: '#047857', fontWeight: 750 }} />) : <Chip size="small" label="No operational evidence found" color="warning" />}
    </Stack>
  );
}

function EvidenceGroup({ group }: { group: AssistantEvidenceGroup }) {
  const [expanded, setExpanded] = useState(group.label !== 'Documentation');
  return (
    <Card variant="outlined" sx={{ borderRadius: '8px' }}>
      <CardContent sx={{ p: 1.6, '&:last-child': { pb: 1.6 } }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" onClick={() => setExpanded(!expanded)} sx={{ cursor: 'pointer' }}>
          <Typography sx={{ fontWeight: 900 }}>{expanded ? '▾' : '▸'} {group.label}</Typography>
          <Chip size="small" label={group.count} />
        </Stack>
        {expanded ? (
          <Stack spacing={1.2} sx={{ mt: 1.4 }}>
            {group.sources.map((source) => (
              <Box key={`${source.reference}-${source.title}`} sx={{ p: 1.2, border: `1px solid ${ui.border}`, borderRadius: '8px', bgcolor: 'var(--os-surface)' }}>
                <Stack direction="row" justifyContent="space-between" spacing={1}>
                  <Box>
                    <Typography sx={{ fontWeight: 850, fontSize: 14 }}>{source.title}</Typography>
                    {source.section ? <Typography sx={{ color: ui.muted, fontSize: 12, fontWeight: 700 }}>{source.section}</Typography> : null}
                  </Box>
                  <Typography sx={{ color: ui.muted, fontSize: 12 }}>{Math.round(source.score * 100)}%</Typography>
                </Stack>
                {source.quote ? (
                  <Typography sx={{ fontSize: 12, mt: 0.8, pl: 1, borderLeft: `3px solid ${ui.border}`, whiteSpace: 'pre-wrap', fontFamily: source.quote.startsWith('```') || source.quote.includes('\n```') ? 'monospace' : undefined }}>
                    {source.quote}
                  </Typography>
                ) : source.summary ? (
                  <Typography sx={{ color: ui.muted, fontSize: 12, mt: 0.5, whiteSpace: 'pre-line', display: '-webkit-box', WebkitLineClamp: 4, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                    {source.summary}
                  </Typography>
                ) : null}
                <Divider sx={{ my: 1 }} />
                {source.reference.startsWith('/') ? (
                  <Button component={RouterLink} to={source.reference} size="small" endIcon={<OpenInNewRoundedIcon />} sx={{ p: 0, textTransform: 'none', fontWeight: 800 }}>Open</Button>
                ) : (
                  <Typography sx={{ color: ui.muted, fontSize: 12 }}>{source.reference}</Typography>
                )}
              </Box>
            ))}
          </Stack>
        ) : null}
      </CardContent>
    </Card>
  );
}

function listPaths(changes: KnowledgeChanges, max = 3): string {
  const paths = [...changes.added, ...changes.changed, ...changes.removed];
  return paths.length > max ? `${paths.slice(0, max).join(', ')} and ${paths.length - max} more` : paths.join(', ');
}

function reindexDetail(result: KnowledgeReindexResult): string {
  const parts = [
    result.added.length ? `New: ${result.added.join(', ')}` : '',
    result.changed.length ? `Updated: ${result.changed.join(', ')}` : '',
    result.removed.length ? `Removed: ${result.removed.join(', ')}` : '',
    `${result.unchanged_documents} other docs unchanged`,
    `took ${(result.duration_ms / 1000).toFixed(1)}s`,
  ];
  return parts.filter(Boolean).join(' · ');
}

function ReindexResultBanner({ result, authoring, onClose }: { result: KnowledgeReindexResult; authoring: boolean; onClose: () => void }) {
  const changed = result.added.length + result.changed.length + result.removed.length;
  const testable = result.added.length + result.changed.length;
  return (
    <Alert
      severity="success"
      onClose={onClose}
      sx={{ mt: 1.5 }}
      action={
        authoring && testable ? (
          <Button component={RouterLink} to={DOCS_CHECK_PATH} color="inherit" size="small" sx={{ fontWeight: 800, whiteSpace: 'nowrap' }}>
            Test the new docs →
          </Button>
        ) : undefined
      }
    >
      <AlertTitle sx={{ fontWeight: 850, mb: 0.2 }}>
        {changed ? 'Docs reindexed just now. Answers now include your changes.' : 'Docs were already up to date. Nothing needed reindexing.'}
      </AlertTitle>
      {reindexDetail(result)}
    </Alert>
  );
}

function ReindexHelp() {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  return (
    <>
      <IconButton aria-label="What does Reindex docs do?" aria-expanded={Boolean(anchor)} onClick={(event) => setAnchor(event.currentTarget)} sx={{ border: `1px solid ${ui.border}` }}>
        <HelpOutlineRoundedIcon fontSize="small" />
      </IconButton>
      <Popover
        open={Boolean(anchor)}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        slotProps={{ paper: { sx: { p: 2, maxWidth: 380, borderRadius: '10px' } } }}
      >
        <Typography sx={{ fontWeight: 850, mb: 1 }}>What does Reindex docs do?</Typography>
        <Stack spacing={1.2} sx={{ fontSize: 14 }}>
          <Typography sx={{ fontSize: 14 }}>
            Ask Ops Signals answers product questions from this project's <b>README.md</b> and <b>docs/</b> folder. It reads them when the backend starts.
          </Typography>
          <Typography sx={{ fontSize: 14 }}><b>Use it when</b> you added or edited a doc and want answers to include it, without restarting.</Typography>
          <Typography sx={{ fontSize: 14 }}><b>Not needed</b> right after a restart, or when no docs changed. A number on the button shows when some did.</Typography>
          <Typography sx={{ fontSize: 14 }}><b>Safe to click anytime.</b> Only changed docs are re-read, it takes a second or two, and findings, cases and metrics are never touched.</Typography>
        </Stack>
      </Popover>
    </>
  );
}

function AnswerFeedback({ question, response, conversationId }: { question: string; response: AssistantChatResponse; conversationId: string | null }) {
  const [feedbackId, setFeedbackId] = useState<number | null>(null);
  const [helpful, setHelpful] = useState<boolean | null>(null);
  const [reason, setReason] = useState<AssistantFeedbackReason | null>(null);
  const send = useMutation({
    mutationFn: (value: boolean) =>
      api.sendAssistantFeedback({
        question,
        helpful: value,
        answer: response.answer,
        conversation_id: conversationId,
        ai_synthesis_used: response.ai_synthesis_used,
        cited: response.sources.slice(0, 3).map((source) => source.reference).filter(Boolean),
      }),
    onSuccess: (saved) => setFeedbackId(saved.id),
  });
  const explain = useMutation({
    mutationFn: (value: AssistantFeedbackReason) => api.updateAssistantFeedback(feedbackId as number, { reason: value }),
  });

  const choose = (value: boolean) => {
    if (helpful !== null) return;
    setHelpful(value);
    send.mutate(value);
  };

  return (
    <Stack spacing={1} sx={{ mt: 1.2, pt: 1.2, borderTop: `1px solid ${ui.border}` }}>
      <Stack direction="row" spacing={1} alignItems="center">
        <Typography sx={{ fontSize: 13, color: ui.muted }}>Did this answer your question?</Typography>
        {/* Not `disabled` once chosen: that greys out the icon and hides which one was picked. */}
        <IconButton size="small" aria-label="Yes, it did" aria-pressed={helpful === true} aria-disabled={helpful !== null} onClick={() => choose(true)} sx={{ color: helpful === true ? 'var(--os-ink-green)' : helpful === false ? '#cbd5e1' : undefined }}>
          {helpful === true ? <ThumbUpAltRoundedIcon fontSize="small" /> : <ThumbUpOffAltRoundedIcon fontSize="small" />}
        </IconButton>
        <IconButton size="small" aria-label="No, it didn't" aria-pressed={helpful === false} aria-disabled={helpful !== null} onClick={() => choose(false)} sx={{ color: helpful === false ? '#c2410c' : helpful === true ? '#cbd5e1' : undefined }}>
          {helpful === false ? <ThumbDownAltRoundedIcon fontSize="small" /> : <ThumbDownOffAltRoundedIcon fontSize="small" />}
        </IconButton>
        {helpful === true && send.isSuccess ? <Typography sx={{ fontSize: 13, color: 'var(--os-ink-green)', fontWeight: 700 }}>Thanks</Typography> : null}
        {send.isError ? <Typography sx={{ fontSize: 13, color: 'var(--os-ink-red)' }}>Couldn't save feedback</Typography> : null}
      </Stack>
      {helpful === false && feedbackId !== null ? (
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          <Typography sx={{ fontSize: 13, color: ui.muted }}>What was wrong?</Typography>
          {feedbackReasons.map((option) => (
            <Chip
              key={option.value}
              label={option.label}
              size="small"
              clickable={reason === null}
              variant={reason === option.value ? 'filled' : 'outlined'}
              color={reason === option.value ? 'warning' : 'default'}
              onClick={reason === null ? () => { setReason(option.value); explain.mutate(option.value); } : undefined}
            />
          ))}
          {explain.isSuccess ? <Typography sx={{ fontSize: 13, color: 'var(--os-ink-green)', fontWeight: 700 }}>Thanks - saved for review</Typography> : null}
          {explain.isError ? <Typography sx={{ fontSize: 13, color: 'var(--os-ink-red)' }}>Couldn't save the reason</Typography> : null}
        </Stack>
      ) : null}
    </Stack>
  );
}

function SystemsExamples({ onAsk }: { onAsk: (question: string) => void }) {
  const starters = useQuery({ queryKey: ['assistant-starters'], queryFn: api.starterQuestions, retry: false });
  const empty = starters.data && !starters.data.has_data;
  return (
    <Box sx={{ p: 2, border: empty ? '1px dashed var(--os-border-strong)' : `1px solid ${ui.border}`, borderRadius: '8px', bgcolor: empty ? 'var(--os-surface-alt)' : 'var(--os-surface)' }}>
      <Typography sx={{ fontWeight: 850 }}>About your systems</Typography>
      {starters.isPending ? (
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1.2, color: ui.muted }}>
          <CircularProgress size={16} />
          <Typography sx={{ fontSize: 13 }}>Looking at what's been analysed…</Typography>
        </Stack>
      ) : starters.isError ? (
        <Typography sx={{ color: ui.muted, fontSize: 13, mt: 0.5 }}>
          Couldn't load examples. Ask about a service, metric, finding or case by name.
        </Typography>
      ) : empty ? (
        <Stack spacing={1.2} sx={{ mt: 0.8 }}>
          <Typography sx={{ fontSize: 14 }}>Nothing has been analysed yet, so there are no findings or cases to ask about.</Typography>
          <Typography sx={{ color: ui.muted, fontSize: 13 }}>Load the demo data to try it in seconds, or connect Prometheus, OTLP or Alertmanager.</Typography>
          <LoadDemoDataButton />
          <Button component={RouterLink} to="/integrations" size="small" sx={{ alignSelf: 'flex-start', p: 0, textTransform: 'none', fontWeight: 750 }}>
            Connect a source →
          </Button>
        </Stack>
      ) : (
        <>
          <Typography sx={{ color: ui.muted, fontSize: 13, mb: 1.2 }}>From what was analysed most recently</Typography>
          <Stack spacing={1} alignItems="flex-start">
            {starters.data.questions.map((question) => (
              <Chip key={question} label={question} clickable onClick={() => onAsk(question)} sx={{ fontWeight: 700, maxWidth: '100%', height: 'auto', py: 0.6, '& .MuiChip-label': { whiteSpace: 'normal' } }} />
            ))}
          </Stack>
        </>
      )}
    </Box>
  );
}

function KnowledgeCard({ status, pendingCount }: { status?: KnowledgeStatus; pendingCount: number }) {
  if (!status) return null;
  const last = status.last_bootstrap;
  return (
    <Box sx={{ mt: 2, p: 1.6, border: `1px solid ${ui.border}`, borderRadius: '8px' }}>
      <Typography sx={{ fontWeight: 900, mb: 1 }}>What the assistant knows</Typography>
      <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 1 }}>
        <Box sx={{ p: 1.2, bgcolor: 'var(--os-surface-alt)', borderRadius: '6px' }}>
          <Typography sx={{ fontSize: 20, fontWeight: 850 }}>{status.document_count}</Typography>
          <Typography sx={{ fontSize: 12, color: ui.muted }}>docs read</Typography>
        </Box>
        <Box sx={{ p: 1.2, bgcolor: pendingCount ? '#eef4ff' : 'var(--os-surface-alt)', borderRadius: '6px' }}>
          <Typography sx={{ fontSize: 20, fontWeight: 850, color: pendingCount ? '#1d4ed8' : undefined }}>{pendingCount}</Typography>
          <Typography sx={{ fontSize: 12, color: pendingCount ? '#1e3a8a' : ui.muted }}>changed since</Typography>
        </Box>
      </Box>
      <Typography sx={{ fontSize: 12, color: ui.muted, mt: 1 }}>
        {last ? `Last read ${new Date(last.started_at).toLocaleString()}` : 'Read when the backend started'}. README.md and everything under docs/ except docs/archive/.
      </Typography>
    </Box>
  );
}

function TipsCard() {
  return (
    <Box sx={{ mt: 2, p: 1.6, border: `1px solid ${ui.border}`, borderRadius: '8px' }}>
      <Typography sx={{ fontWeight: 900, mb: 1 }}>Tips</Typography>
      <Stack spacing={1}>
        <Typography sx={{ fontSize: 13 }}><b>Name a service or metric</b> for questions about your data: "latency on checkout-api last night".</Typography>
        <Typography sx={{ fontSize: 13 }}><b>Check the quote.</b> Every docs answer shows the passage it used and links to its section.</Typography>
        <Typography sx={{ fontSize: 13 }}><b>Wrong answer?</b> Use the thumbs-down under it. Flagged questions help improve the docs.</Typography>
      </Stack>
    </Box>
  );
}
