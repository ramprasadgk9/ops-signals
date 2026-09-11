import { useMemo, useState } from 'react';
import { Alert, Box, Button, Card, CardContent, Chip, CircularProgress, Divider, IconButton, Stack, TextField, Typography } from '@mui/material';
import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded';
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded';
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded';
import SendRoundedIcon from '@mui/icons-material/SendRounded';
import OpenInNewRoundedIcon from '@mui/icons-material/OpenInNewRounded';
import { useMutation } from '@tanstack/react-query';
import { Link as RouterLink } from 'react-router-dom';
import { api } from '../api/queries';
import { ErrorState } from '../components/ErrorState';
import { WorkspacePanel } from '../standalone/components';
import { ui } from '../standalone/theme';
import type { AssistantChatResponse, AssistantEvidenceGroup } from '../types';

type ChatMessage = {
  role: 'user' | 'assistant';
  content: string;
  response?: AssistantChatResponse;
};

const starterPrompts = [
  'Any cases related to trend signal?',
  'Have we seen this before?',
  'What caused checkout CPU trend?',
  'Explain STUMPY',
  'How does Behavior Intelligence work?',
  'What changed yesterday?',
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
    onSuccess: (data) => {
      setConversationId(data.conversation_id);
      setMessages((current) => [...current, { role: 'assistant', content: data.answer, response: data }]);
    },
  });

  const regenerate = () => {
    const lastUser = [...messages].reverse().find((item) => item.role === 'user');
    if (lastUser) sendMessage(lastUser.content);
  };

  return (
    <Box sx={{ pb: 3, height: 'calc(100vh - 120px)', minHeight: 680 }}>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', xl: 'minmax(0, 1fr) 360px' }, gap: 2, height: '100%' }}>
        <WorkspacePanel sx={{ display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden' }}>
          <Box sx={{ px: 3, py: 2.2, borderBottom: `1px solid ${ui.border}` }}>
            <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={1.5}>
              <Box>
                <Typography sx={{ fontSize: 24, fontWeight: 900, color: ui.text }}>Ask Ops Signals</Typography>
                <Typography sx={{ color: ui.muted, fontSize: 14 }}>Operational assistant for cases, findings, memory, behavior intelligence, and docs.</Typography>
              </Box>
              <Stack direction="row" spacing={1}>
                <Button startIcon={<RefreshRoundedIcon />} variant="outlined" onClick={regenerate} disabled={!messages.some((item) => item.role === 'user') || mutation.isPending}>Regenerate</Button>
                <Button startIcon={<DeleteOutlineRoundedIcon />} variant="outlined" onClick={() => { setMessages([]); setConversationId(null); }}>Clear</Button>
              </Stack>
            </Stack>
          </Box>

          <Box sx={{ flex: 1, overflowY: 'auto', px: { xs: 2, md: 5 }, py: 3, bgcolor: '#fbfdff' }}>
            {!messages.length ? (
              <Stack spacing={2.5} sx={{ maxWidth: 760, mx: 'auto', mt: 6 }}>
                <Typography sx={{ fontSize: 28, fontWeight: 900, textAlign: 'center' }}>What do you want to investigate?</Typography>
                <Typography sx={{ color: ui.muted, textAlign: 'center' }}>Ask about similar incidents, current findings, behavior patterns, analyzer output, or architecture.</Typography>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap justifyContent="center">
                  {starterPrompts.map((prompt) => <Chip key={prompt} label={prompt} clickable onClick={() => sendMessage(prompt)} sx={{ fontWeight: 750 }} />)}
                </Stack>
              </Stack>
            ) : (
              <Stack spacing={2.2} sx={{ maxWidth: 900, mx: 'auto' }}>
                {messages.map((item, index) => (
                  <Box key={index} sx={{ alignSelf: item.role === 'user' ? 'flex-end' : 'stretch', maxWidth: item.role === 'user' ? '72%' : '100%' }}>
                    {item.role === 'assistant' ? <KnowledgeUsed response={item.response} /> : null}
                    <Box sx={{ px: 2, py: 1.6, borderRadius: '12px', bgcolor: item.role === 'user' ? '#0f766e' : '#fff', color: item.role === 'user' ? '#fff' : ui.text, border: item.role === 'assistant' ? `1px solid ${ui.border}` : 'none' }}>
                      <Typography sx={{ whiteSpace: 'pre-line', lineHeight: 1.65 }}>{item.content}</Typography>
                      {item.role === 'assistant' ? (
                        <Stack direction="row" spacing={0.5} sx={{ mt: 1 }}>
                          <IconButton size="small" onClick={() => navigator.clipboard?.writeText(item.content)}><ContentCopyRoundedIcon fontSize="small" /></IconButton>
                        </Stack>
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

          <Box sx={{ p: 2, borderTop: `1px solid ${ui.border}`, bgcolor: '#fff' }}>
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
          sx={response?.ai_synthesis_used ? { bgcolor: '#f5f3ff', color: '#6d28d9', fontWeight: 750 } : { bgcolor: '#f1f5f9', color: '#475569', fontWeight: 750 }}
        />
      ) : null}
      {used.length ? used.map((item) => <Chip key={item} size="small" label={`✓ ${item}`} sx={{ bgcolor: '#ecfdf5', color: '#047857', fontWeight: 750 }} />) : <Chip size="small" label="No operational evidence found" color="warning" />}
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
              <Box key={`${source.reference}-${source.title}`} sx={{ p: 1.2, border: `1px solid ${ui.border}`, borderRadius: '8px', bgcolor: '#fbfdff' }}>
                <Stack direction="row" justifyContent="space-between" spacing={1}>
                  <Typography sx={{ fontWeight: 850, fontSize: 14 }}>{source.title}</Typography>
                  <Typography sx={{ color: ui.muted, fontSize: 12 }}>{Math.round(source.score * 100)}%</Typography>
                </Stack>
                {source.summary ? <Typography sx={{ color: ui.muted, fontSize: 12, mt: 0.5 }}>{source.summary}</Typography> : null}
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
